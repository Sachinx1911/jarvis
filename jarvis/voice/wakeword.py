"""Wake word ("hey jarvis") behind an interface, off by default (config wake_word.enabled).

openWakeWord (https://github.com/dscripka/openWakeWord) has a pre-trained "hey_jarvis" model.
Status checked 2026-10-10: last release 0.6.0 (2024-02-11); on Windows and macOS it runs on
onnxruntime (tflite is Linux-only); it pulls in scipy and scikit-learn; macOS is not listed as
tested. Its pre-trained models are CC BY-NC-SA 4.0 (personal use is fine). Models are
downloaded only by `jarvis voice setup` (openwakeword.utils.download_models, from the project's
GitHub release) into JARVIS_HOME/data/models/openwakeword/; Jarvis never downloads them by itself.
Checked on the M4 Mac (2026-10-10): 0.6.0 installs on Python 3.13 and "hey_jarvis" loads on onnxruntime.

Voice verification ("only Sachin's voice") uses openWakeWord's custom verifier, which must be
trained on recordings of Sachin. That is later work: it needs real voice clips, which never
go into this public repo.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jarvis.voice.base import VoiceUnavailable
from jarvis.voice.models import HEY_JARVIS

PACKAGE_HINT = ('pip install -e ".[wakeword]" (openwakeword 0.6.0; pulls onnxruntime, scipy, scikit-learn), '
                "then `jarvis voice setup --model hey_jarvis`")
FEATURE_MODELS = ("melspectrogram.onnx", "embedding_model.onnx")


def models_dir(home: Path) -> Path:
    return HEY_JARVIS.path(home)


def openwakeword_installed() -> bool:
    try:
        import openwakeword  # noqa: F401
    except ImportError:
        return False
    return True


def download_wakeword(home: Path, model: str = "hey_jarvis") -> Path:
    """Fetch the wake-word model and its two feature models (a few MB) into data/models/openwakeword/."""
    import openwakeword.utils

    dest = models_dir(home)
    dest.mkdir(parents=True, exist_ok=True)
    openwakeword.utils.download_models([model], target_directory=str(dest))
    return dest


def find_model(folder: Path | None, model: str) -> Path | None:
    """The .onnx file for a model name (e.g. hey_jarvis -> hey_jarvis_v0.1.onnx), or an explicit path."""
    if model.endswith(".onnx") and Path(model).is_file():
        return Path(model)
    if folder is None or not folder.is_dir():
        return None
    matches = sorted(folder.glob(f"{model}*.onnx"))
    return matches[-1] if matches else None


class OpenWakeWordDetector:
    name = "openwakeword"

    def __init__(self, model: str = "hey_jarvis", threshold: float = 0.5, factory: Any = None,
                 models_dir: Path | None = None):
        self.model_name = model
        self.threshold = threshold
        self._factory = factory
        self.models_dir = models_dir
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
            path = find_model(self.models_dir, self.model_name)
            features = [self.models_dir / f for f in FEATURE_MODELS] if self.models_dir else []
            try:
                if path is not None and features and all(f.is_file() for f in features):
                    # Jarvis's own copy (data/models/openwakeword), not the package folder.
                    self._model = factory(wakeword_models=[str(path)], inference_framework="onnx",
                                          melspec_model_path=str(features[0]),
                                          embedding_model_path=str(features[1]))
                else:
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


def make_wakeword(cfg: dict[str, Any], home: Path | None = None):
    ww = cfg.get("wake_word", {})
    if not ww.get("enabled", False):
        return None
    if ww.get("engine", "openwakeword") == "openwakeword":
        if home is None:
            from jarvis.paths import default_paths

            home = default_paths().home
        return OpenWakeWordDetector(ww.get("model", "hey_jarvis"), float(ww.get("threshold", 0.5)),
                                    models_dir=models_dir(home))
    raise ValueError(f"unknown wake-word engine {ww.get('engine')!r}")
