"""Wake word ("hey jarvis") behind an interface, off by default (config wake_word.enabled).

openWakeWord (https://github.com/dscripka/openWakeWord) has a pre-trained "hey_jarvis" model.
Status checked 2026-10-10: last release 0.6.0 (2024-02-11); on Windows and macOS it runs on
onnxruntime (tflite is Linux-only); it pulls in scipy and scikit-learn; macOS is not listed as
tested. Its pre-trained models are CC BY-NC-SA 4.0 (personal use is fine). Models are
downloaded with openwakeword.utils.download_models(); Jarvis never downloads them by itself.

Voice verification ("only Sachin's voice") uses openWakeWord's custom verifier, which must be
trained on recordings of Sachin. That is later work: it needs real voice clips, which never
go into this public repo.
"""

from __future__ import annotations

from typing import Any

from jarvis.voice.base import VoiceUnavailable

PACKAGE_HINT = ("pip install openwakeword==0.6.0 (pulls onnxruntime, scipy, scikit-learn), then "
                "python -c \"import openwakeword.utils as u; u.download_models(['hey_jarvis'])\"")


class OpenWakeWordDetector:
    name = "openwakeword"

    def __init__(self, model: str = "hey_jarvis", threshold: float = 0.5, factory: Any = None):
        self.model_name = model
        self.threshold = threshold
        self._factory = factory
        self._model: Any = None

    def _load(self) -> Any:
        if self._model is None:
            factory = self._factory
            if factory is None:
                try:
                    from openwakeword.model import Model
                except ImportError as e:
                    raise VoiceUnavailable(f"openWakeWord is not installed: {PACKAGE_HINT}") from e
                factory = Model
            try:
                self._model = factory(wakeword_models=[self.model_name], inference_framework="onnx")
            except (FileNotFoundError, ValueError) as e:
                raise VoiceUnavailable(f"wake-word model {self.model_name!r} is missing: {PACKAGE_HINT}") from e
        return self._model

    def process(self, frame: bytes) -> bool:
        import numpy as np  # installed with openwakeword

        scores = self._load().predict(np.frombuffer(frame, dtype=np.int16))
        return any(score >= self.threshold for score in scores.values())

    def reset(self) -> None:
        if self._model is not None and hasattr(self._model, "reset"):
            self._model.reset()


class FakeWakeWord:
    name = "fake"

    def __init__(self, trigger_on: bytes = b"WAKE"):
        self.trigger_on = trigger_on
        self.heard = 0

    def process(self, frame: bytes) -> bool:
        self.heard += 1
        return frame == self.trigger_on

    def reset(self) -> None:
        pass


def make_wakeword(cfg: dict[str, Any]):
    ww = cfg.get("wake_word", {})
    if not ww.get("enabled", False):
        return None
    if ww.get("engine", "openwakeword") == "openwakeword":
        return OpenWakeWordDetector(ww.get("model", "hey_jarvis"), float(ww.get("threshold", 0.5)))
    raise ValueError(f"unknown wake-word engine {ww.get('engine')!r}")
