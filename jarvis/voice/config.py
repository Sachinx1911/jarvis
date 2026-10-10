"""Voice settings: config/voice.yaml, with machine overrides under `voice_file` in config/local.yaml."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from jarvis.paths import CONFIG_DIR

DEFAULTS: dict[str, Any] = {
    "stt": {"engine": "faster_whisper", "model": "small", "device": "cpu", "compute_type": "int8",
            "language": "auto", "min_confidence": 0.45, "marathi_engine": "indicconformer"},
    "tts": {"engine": "auto", "voice": "", "rate": 0,
            "marathi": {"offline_engine": "mms_tts", "cloud_enabled": False, "engine": "edge_tts",
                        "voice": "mr-IN-ManoharNeural", "max_privacy": "P1"}},
    "recorder": {"sample_rate": 16000, "device": None, "max_seconds": 30},
    "barge_in": "key",
    "vad": {"threshold_rms": 900, "min_speech_ms": 240, "end_silence_ms": 900},
    "wake_word": {"enabled": False, "engine": "openwakeword", "model": "hey_jarvis", "threshold": 0.5},
    "store_audio": False,
}


def _read(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a mapping")
    return data


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def load_voice_config(config_dir: Path = CONFIG_DIR) -> dict[str, Any]:
    cfg = _merge(DEFAULTS, _read(config_dir / "voice.yaml"))
    return _merge(cfg, _read(config_dir / "local.yaml").get("voice_file", {}))
