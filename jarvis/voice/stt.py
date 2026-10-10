"""Speech-to-text engines.

faster-whisper (local Whisper on CTranslate2) is the default: CPU wheels for Windows and
macOS Apple Silicon on Python 3.12-3.14, no torch, int8 on CPU, Silero VAD bundled.
https://github.com/SYSTRAN/faster-whisper  https://pypi.org/project/faster-whisper/

Marathi: plain Whisper is weak at Marathi (FLEURS WER 38% for large-v2), so Marathi speech goes
to AI4Bharat IndicConformer (MIT), run as ONNX int8 through onnx-asr (numpy + onnxruntime, no
torch). LanguageRouter picks the engine per utterance: config `stt.language` en | mr | auto.

Model weights are a separate download (hundreds of MB). They are fetched only by
`jarvis voice setup`; loading never downloads (local_files_only / a local folder only).
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

from jarvis.voice.base import SAMPLE_RATE, Audio, Transcript, VoiceUnavailable
from jarvis.voice.models import INDICCONFORMER_MR, VoiceModel

# Hugging Face repos used by faster_whisper.utils._MODELS, with sizes measured 2026-10-10
# from the Hugging Face API (sum of the repo files).
WHISPER_MODELS: dict[str, tuple[str, int]] = {
    "base": ("Systran/faster-whisper-base", 148),
    "small": ("Systran/faster-whisper-small", 486),
    "small.en": ("Systran/faster-whisper-small.en", 486),
    "medium": ("Systran/faster-whisper-medium", 1531),
    "large-v3-turbo": ("mobiuslabsgmbh/faster-whisper-large-v3-turbo", 1622),
}
PACKAGE_HINT = "pip install faster-whisper==1.2.1 (about 80 MB with ctranslate2, onnxruntime, av)"


def models_dir(home: Path) -> Path:
    return home / "data" / "models" / "whisper"


def model_path(home: Path, model: str) -> Path:
    return models_dir(home) / model


def model_present(home: Path, model: str) -> bool:
    return (model_path(home, model) / "model.bin").exists()


def setup_hint(model: str) -> str:
    size = WHISPER_MODELS.get(model, ("", 0))[1]
    return f"run `jarvis voice setup` to download Whisper model {model!r}" + (f" ({size} MB)" if size else "")


def faster_whisper_installed() -> bool:
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return False
    return True


class FasterWhisperSTT:
    """Local Whisper. Loads lazily on the first transcription."""

    name = "faster_whisper"
    cloud = False

    def __init__(self, home: Path, model: str = "small", device: str = "cpu", compute_type: str = "int8"):
        self.home = home
        self.model = model
        self.device = device
        self.compute_type = compute_type
        self._whisper: Any = None
        self.last_language_probs: dict[str, float] = {}

    def check(self) -> None:
        if not faster_whisper_installed():
            raise VoiceUnavailable(f"faster-whisper is not installed: {PACKAGE_HINT}; then {setup_hint(self.model)}")
        if not model_present(self.home, self.model):
            raise VoiceUnavailable(f"Whisper model {self.model!r} is not downloaded: {setup_hint(self.model)}")

    def _load(self) -> Any:
        if self._whisper is None:
            self.check()
            from faster_whisper import WhisperModel

            self._whisper = WhisperModel(str(model_path(self.home, self.model)), device=self.device,
                                         compute_type=self.compute_type, local_files_only=True)
        return self._whisper

    def _segments(self, audio: Audio, language: str | None) -> tuple[Any, Any]:
        """Start a transcription. Language detection runs now; the segments decode lazily."""
        if audio.sample_rate != SAMPLE_RATE:
            raise ValueError(f"expected {SAMPLE_RATE} Hz audio, got {audio.sample_rate}")
        whisper = self._load()
        samples = pcm_to_float(audio)
        segments, info = whisper.transcribe(samples, language=language, beam_size=5, vad_filter=True)
        # Every language's probability from the detection step (None when a language was given).
        self.last_language_probs = dict(getattr(info, "all_language_probs", None) or [])
        return segments, info

    def transcribe(self, audio: Audio, language_hint: str | None = None) -> Transcript:
        segments, info = self._segments(audio, language_hint)
        return transcript_from_segments(list(segments), info.language, info.language_probability)

    def transcribe_if_english(self, audio: Audio) -> tuple[Transcript | None, str, float]:
        """Detect the language. English: transcribe it. Anything else: (None, language, p) without decoding."""
        segments, info = self._segments(audio, None)
        if info.language != "en":
            return None, info.language, float(info.language_probability or 0.0)
        t = transcript_from_segments(list(segments), info.language, info.language_probability)
        return t, info.language, float(info.language_probability or 0.0)


def pcm_to_float(audio: Audio) -> Any:
    import numpy as np  # installed with faster-whisper and onnx-asr

    return np.frombuffer(audio.pcm[: len(audio.pcm) // 2 * 2], dtype=np.int16).astype(np.float32) / 32768.0


def transcript_from_segments(segments: list[Any], language: str | None, language_probability: float) -> Transcript:
    """Map Whisper scores to one 0..1 confidence: exp(mean avg_logprob), weighted by text length.

    Segments that are most likely silence (no_speech_prob > 0.6) are dropped.
    """
    kept = [s for s in segments if getattr(s, "no_speech_prob", 0.0) <= 0.6 and s.text.strip()]
    text = " ".join(s.text.strip() for s in kept).strip()
    if not kept:
        return Transcript("", language, 0.0)
    weights = [max(1, len(s.text.strip())) for s in kept]
    mean_logprob = sum(s.avg_logprob * w for s, w in zip(kept, weights)) / sum(weights)
    confidence = math.exp(min(0.0, mean_logprob))
    if language_probability and language_probability < 0.5:
        confidence *= language_probability * 2  # unsure of the language: be less sure of the words
    return Transcript(text, language, round(confidence, 3))


# ---- Marathi: IndicConformer (ONNX) ----

ONNX_ASR_HINT = "pip install onnx-asr==0.12.0 (4 MB; uses numpy and onnxruntime from faster-whisper)"


def onnx_asr_installed() -> bool:
    try:
        import onnx_asr  # noqa: F401
    except ImportError:
        return False
    return True


def _load_onnx_asr(path: Path) -> Any:
    import onnx_asr

    # A local folder only (offline); CTC export, int8 weights, CPU.
    model = onnx_asr.load_model("nemo-conformer-ctc", path, quantization="int8",
                                providers=["CPUExecutionProvider"])
    return model.with_timestamps()  # adds per-token log-probabilities, used for the confidence


def transcript_from_ctc(text: str, logprobs: list[float] | None, language: str = "mr") -> Transcript:
    """Map greedy-CTC token log-probabilities to one 0..1 confidence: exp(mean token logprob)."""
    text = " ".join(text.split())
    if not text:
        return Transcript("", language, 0.0)
    if not logprobs:
        return Transcript(text, language, 0.5)  # no scores: neither sure nor unsure
    mean = sum(logprobs) / len(logprobs)
    return Transcript(text, language, round(math.exp(min(0.0, mean)), 3))


class IndicConformerSTT:
    """Local Marathi speech-to-text: AI4Bharat IndicConformer, ONNX int8. Loads lazily."""

    name = "indicconformer"
    cloud = False

    def __init__(self, home: Path, model: VoiceModel = INDICCONFORMER_MR,
                 loader: Callable[[Path], Any] | None = None, installed: Callable[[], bool] | None = None):
        self.home = home
        self.model = model
        self._loader = loader or _load_onnx_asr
        self._installed = installed or onnx_asr_installed
        self._asr: Any = None

    def check(self) -> None:
        if not self._installed():
            raise VoiceUnavailable(f"onnx-asr is not installed (needed for Marathi speech): {ONNX_ASR_HINT}")
        if not self.model.present(self.home):
            raise VoiceUnavailable(f"the Marathi speech model is not downloaded: run `jarvis voice setup` "
                                   f"({self.model.key}, {self.model.mb} MB)")

    def _load(self) -> Any:
        if self._asr is None:
            self.check()
            self._asr = self._loader(self.model.path(self.home))
        return self._asr

    def transcribe(self, audio: Audio, language_hint: str | None = None) -> Transcript:
        asr = self._load()
        result = asr.recognize(pcm_to_float(audio), sample_rate=audio.sample_rate)
        return transcript_from_ctc(result.text, getattr(result, "logprobs", None))


MARATHI_ENGINES = ("none", "indicconformer")


def make_marathi_stt(cfg: dict[str, Any], home: Path):
    engine = (cfg.get("stt", {}).get("marathi_engine") or "none").lower()
    if engine == "none":
        return None
    if engine == "indicconformer":
        return IndicConformerSTT(home)
    raise ValueError(f"unknown Marathi stt engine {engine!r} (choose: {', '.join(MARATHI_ENGINES)})")


# ---- language routing ----

# Whisper's language guess at or above this goes straight to the Marathi engine.
SURE_MARATHI = 0.5


class LanguageRouter:
    """One speech-to-text front for English and Marathi (config `stt.language`):

    en   = Whisper, English only.
    mr   = the Marathi engine only.
    auto = Whisper detects the language (cheap: segments are never decoded for non-English).
           English stays with Whisper. A sure Marathi guess goes to the Marathi engine. Anything
           else (Whisper often labels Marathi as Hindi, and accented English as Hindi or Urdu)
           goes to whichever of English and Marathi Whisper rated more likely.
    A per-call language hint ("en" / "mr") overrides the mode.
    """

    cloud = False

    def __init__(self, english: Any, marathi: Any, mode: str = "auto"):
        mode = (mode or "auto").lower()
        if mode not in ("auto", "en", "mr"):
            raise ValueError(f"stt.language must be auto, en or mr, not {mode!r}")
        self.english = english
        self.marathi = marathi
        self.mode = mode
        self.name = f"{english.name}+{marathi.name}"

    def check(self) -> None:
        """Raise only when the engine this mode always needs is missing (English keeps working
        in auto mode without the Marathi model; Marathi speech then says how to set it up)."""
        needed = self.marathi if self.mode == "mr" else self.english
        if hasattr(needed, "check"):
            needed.check()

    def marathi_ready(self) -> tuple[bool, str]:
        try:
            if hasattr(self.marathi, "check"):
                self.marathi.check()
        except VoiceUnavailable as e:
            return False, str(e)
        return True, "ready"

    def transcribe(self, audio: Audio, language_hint: str | None = None) -> Transcript:
        mode = (language_hint or self.mode).lower()
        if mode == "en":
            return replace(self.english.transcribe(audio, "en"), engine=self.english.name)
        if mode == "mr":
            return replace(self.marathi.transcribe(audio, "mr"), engine=self.marathi.name)
        t, lang, prob = self.english.transcribe_if_english(audio)
        if t is not None:
            return replace(t, engine=self.english.name)
        if not (lang == "mr" and prob >= SURE_MARATHI):
            # Whisper named another language (often Hindi or Urdu, both for Marathi speech and for
            # short English phrases in an Indian accent; seen 2026-10-11: "how are you" went to the
            # Marathi engine). Jarvis expects only English or Marathi, so compare just those two
            # guesses. Comparing transcript confidences does not work: IndicConformer writes English
            # speech in Devanagari letters with high confidence.
            probs = getattr(self.english, "last_language_probs", None) or {}
            if probs.get("en", 0.0) > probs.get("mr", 0.0):
                return replace(self.english.transcribe(audio, "en"), engine=self.english.name)
        return replace(self.marathi.transcribe(audio, "mr"), engine=self.marathi.name)


class FakeSTT:
    """Test double: returns scripted transcripts in order."""

    name = "fake"
    cloud = False

    def __init__(self, script: list[Transcript | str] | None = None):
        self.script = deque(script or [])
        self.calls: list[tuple[Audio, str | None]] = []

    def transcribe(self, audio: Audio, language_hint: str | None = None) -> Transcript:
        self.calls.append((audio, language_hint))
        if not self.script:
            return Transcript("", None, 0.0)
        item = self.script.popleft()
        return Transcript(item, "en", 0.95) if isinstance(item, str) else item


def make_stt(cfg: dict[str, Any], home: Path):
    stt = cfg.get("stt", {})
    engine = stt.get("engine", "faster_whisper")
    if engine == "faster_whisper":
        whisper = FasterWhisperSTT(home, stt.get("model", "small"), stt.get("device", "cpu"),
                                   stt.get("compute_type", "int8"))
        marathi = make_marathi_stt(cfg, home)
        if marathi is None:
            return whisper  # no Marathi engine: Whisper handles every language itself
        return LanguageRouter(whisper, marathi, stt.get("language", "auto"))
    if engine == "fake":
        return FakeSTT()
    raise ValueError(f"unknown stt engine {engine!r}")


def language_hint(cfg: dict[str, Any]) -> str | None:
    lang = (cfg.get("stt", {}).get("language") or "auto").lower()
    return None if lang == "auto" else lang
