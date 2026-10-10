"""Offline Marathi voice: Meta MMS-TTS Marathi (VITS, 36M parameters) run as ONNX on this machine.

License: CC-BY-NC 4.0 (non-commercial; Sachin's personal use is fine).
https://huggingface.co/facebook/mms-tts-mar

The model reads Devanagari characters directly (no phonemizer, no uroman). Its alphabet has no
punctuation, no Latin letters and only some ASCII digits, so the text is prepared first:
numbers are spelled out in Marathi words, English words get a rough Devanagari spelling, and
sentences are synthesized one by one with a short pause between them.

Needs only onnxruntime and numpy (both come with faster-whisper). The model files are fetched by
`jarvis voice setup`; nothing is downloaded here.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import unicodedata
import uuid
from pathlib import Path
from typing import Any, Callable

from jarvis.voice.base import SAMPLE_RATE, Audio, DonePlayback, Playback, VoiceUnavailable
from jarvis.voice.models import MMS_TTS_MAR, VoiceModel

PAUSE_SECONDS = 0.25          # silence between sentences
MAX_CHUNK_CHARS = 250         # VITS attention grows with the square of the length: keep chunks short

_ONES = ("शून्य एक दोन तीन चार पाच सहा सात आठ नऊ दहा अकरा बारा तेरा चौदा पंधरा सोळा सतरा अठरा एकोणीस "
         "वीस एकवीस बावीस तेवीस चोवीस पंचवीस सव्वीस सत्तावीस अठ्ठावीस एकोणतीस "
         "तीस एकतीस बत्तीस तेहतीस चौतीस पस्तीस छत्तीस सदतीस अडतीस एकोणचाळीस "
         "चाळीस एक्केचाळीस बेचाळीस त्रेचाळीस चव्वेचाळीस पंचेचाळीस सेहेचाळीस सत्तेचाळीस अठ्ठेचाळीस एकोणपन्नास "
         "पन्नास एक्कावन्न बावन्न त्रेपन्न चोपन्न पंचावन्न छप्पन्न सत्तावन्न अठ्ठावन्न एकोणसाठ "
         "साठ एकसष्ट बासष्ट त्रेसष्ट चौसष्ट पासष्ट सहासष्ट सदुसष्ट अडुसष्ट एकोणसत्तर "
         "सत्तर एक्काहत्तर बाहत्तर त्र्याहत्तर चौऱ्याहत्तर पंच्याहत्तर शहात्तर सत्याहत्तर अठ्ठ्याहत्तर एकोणऐंशी "
         "ऐंशी एक्क्याऐंशी ब्याऐंशी त्र्याऐंशी चौऱ्याऐंशी पंच्याऐंशी शहाऐंशी सत्त्याऐंशी अठ्ठ्याऐंशी एकोणनव्वद "
         "नव्वद एक्क्याण्णव ब्याण्णव त्र्याण्णव चौऱ्याण्णव पंच्याण्णव शहाण्णव सत्त्याण्णव अठ्ठ्याण्णव नव्व्याण्णव").split()
assert len(_ONES) == 100
_SCALES = ((10_000_000, "कोटी"), (100_000, "लाख"), (1000, "हजार"), (100, "शे"))


def marathi_number(n: int) -> str:
    """Spell a whole number in Marathi words (Indian grouping: हजार, लाख, कोटी)."""
    if n < 0:
        return "उणे " + marathi_number(-n)
    if n < 100:
        return _ONES[n]
    words: list[str] = []
    for value, name in _SCALES:
        if n >= value:
            count, n = divmod(n, value)
            if value == 100:
                words.append("शंभर" if count == 1 and not n else f"{_ONES[count]}{name}")
            else:
                words.append(f"{marathi_number(count)} {name}")
    if n:
        words.append(_ONES[n])
    return " ".join(words)


_DEV_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
_NUMBER = re.compile(r"\d+(?:,\d+)*")
_RUPEES = re.compile(r"₹\s*(\d[\d,]*)")
_LATIN_WORD = re.compile(r"[A-Za-z]+")
_SENTENCE_END = re.compile(r"(?<=[।॥.!?;\n])\s*")
# Signs the model's alphabet lacks, mapped to the nearest letters it has.
_SIGN_MAP = str.maketrans({"ॉ": "ो", "ॅ": "े", "ऑ": "ओ", "ॲ": "ए", "ऍ": "ए", "ँ": "ं", "़": None, "‍": None,
                           "‌": None, "ॄ": "ृ", "ॠ": "ऋ"})


def prepare_text(text: str) -> list[str]:
    """Sentences ready for the model: numbers in words, English words in Devanagari, no unknown signs."""
    from jarvis.memory.translit import to_devanagari

    text = unicodedata.normalize("NFC", text).translate(_DEV_DIGITS)
    text = _RUPEES.sub(r"\1 रुपये", text).replace("₹", " रुपये ").replace("%", " टक्के ")
    text = _NUMBER.sub(lambda m: f" {marathi_number(int(m.group().replace(',', '')))} ", text)
    text = _LATIN_WORD.sub(lambda m: to_devanagari(m.group()) or " ", text)
    text = text.translate(_SIGN_MAP)
    chunks: list[str] = []
    for sentence in _SENTENCE_END.split(text):
        sentence = " ".join(sentence.split())
        while len(sentence) > MAX_CHUNK_CHARS:
            cut = sentence.rfind(" ", 0, MAX_CHUNK_CHARS)
            cut = cut if cut > 0 else MAX_CHUNK_CHARS
            chunks.append(sentence[:cut])
            sentence = sentence[cut:].strip()
        if sentence:
            chunks.append(sentence)
    return chunks


class VitsTokenizer:
    """The model's character tokenizer (transformers' VitsTokenizer with add_blank, no uroman)."""

    def __init__(self, vocab: dict[str, int], add_blank: bool = True, blank_id: int = 0):
        self.vocab = vocab
        self.add_blank = add_blank
        self.blank_id = blank_id

    @staticmethod
    def from_dir(path: Path) -> "VitsTokenizer":
        vocab = json.loads((path / "vocab.json").read_text(encoding="utf-8"))
        cfg_file = path / "tokenizer_config.json"
        cfg = json.loads(cfg_file.read_text(encoding="utf-8")) if cfg_file.exists() else {}
        if cfg.get("is_uroman") or cfg.get("phonemize"):
            raise VoiceUnavailable("this MMS model needs uroman or a phonemizer, which Jarvis does not support")
        return VitsTokenizer(vocab, bool(cfg.get("add_blank", True)), vocab.get(cfg.get("pad_token", ""), 0))

    def encode(self, text: str) -> list[int]:
        ids = [self.vocab[c] for c in text.lower() if c in self.vocab]
        while ids and ids[-1] == self.vocab.get(" "):
            ids.pop()
        if not self.add_blank:
            return ids
        out = [self.blank_id] * (2 * len(ids) + 1)
        out[1::2] = ids
        return out


def onnxruntime_installed() -> bool:
    try:
        import numpy  # noqa: F401
        import onnxruntime  # noqa: F401
    except ImportError:
        return False
    return True


def _session(path: Path) -> Any:
    import onnxruntime as ort

    return ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])


class MmsTTS:
    """Speaks Marathi offline. Synthesizes to a temporary WAV, plays it, then deletes it."""

    name = "mms_tts"
    cloud = False

    def __init__(self, home: Path, tmp_dir: Path, popen: Callable[..., Any] = subprocess.Popen,
                 platform: str = sys.platform, model: VoiceModel = MMS_TTS_MAR,
                 session_factory: Callable[[Path], Any] | None = None,
                 installed: Callable[[], bool] = onnxruntime_installed):
        self.home = home
        self.tmp_dir = tmp_dir
        self.popen = popen
        self.platform = platform
        self.model = model
        self._session_factory = session_factory or _session
        self._installed = installed
        self._session: Any = None
        self._tokenizer: VitsTokenizer | None = None

    def check(self) -> None:
        if not self.model.present(self.home):
            raise VoiceUnavailable(f"the offline Marathi voice is not downloaded: run `jarvis voice setup` "
                                   f"({self.model.key}, {self.model.mb} MB)")
        if not self._installed():
            raise VoiceUnavailable("onnxruntime is not installed (it comes with the voice extra): "
                                   'pip install -e ".[voice]"')

    def _load(self) -> tuple[Any, VitsTokenizer]:
        if self._session is None or self._tokenizer is None:
            self.check()
            folder = self.model.path(self.home)
            self._tokenizer = VitsTokenizer.from_dir(folder)
            self._session = self._session_factory(folder / self.model.ready_file)
        return self._session, self._tokenizer

    def synthesize(self, text: str) -> Audio:
        import numpy as np

        session, tokenizer = self._load()
        pause = np.zeros(int(SAMPLE_RATE * PAUSE_SECONDS), dtype=np.float32)
        parts: list[Any] = []
        for chunk in prepare_text(text):
            ids = tokenizer.encode(chunk)
            if len(ids) < 3:
                continue
            input_ids = np.asarray([ids], dtype=np.int64)
            outputs = session.run(None, {"input_ids": input_ids, "attention_mask": np.ones_like(input_ids)})
            parts += [np.asarray(outputs[0], dtype=np.float32).reshape(-1), pause]
        if not parts:
            return Audio(b"")
        wave = np.concatenate(parts[:-1])
        peak = float(np.abs(wave).max()) or 1.0
        pcm = (np.clip(wave / max(peak, 1.0), -1.0, 1.0) * 32767).astype("<i2").tobytes()
        return Audio(pcm, SAMPLE_RATE)

    def speak(self, text: str, language: str = "mr") -> Playback:
        from jarvis.voice.tts import ProcessPlayback, _popen_kwargs, play_file_command

        if not text.strip():
            return DonePlayback()
        audio = self.synthesize(text)
        if not audio.pcm:
            return DonePlayback()
        self.tmp_dir.mkdir(parents=True, exist_ok=True)
        path = self.tmp_dir / f"tts-{uuid.uuid4().hex[:10]}.wav"
        path.write_bytes(audio.to_wav())
        try:
            argv, env = play_file_command(path, self.platform)
            proc = self.popen(argv, env=env, **_popen_kwargs())
        except Exception:
            path.unlink(missing_ok=True)
            raise
        return ProcessPlayback(proc, cleanup=lambda: path.unlink(missing_ok=True))
