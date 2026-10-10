"""Load config/india.yaml with overrides from config/local.yaml (key: india_file)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jarvis.config import _merge, _read_yaml
from jarvis.connectors.config import get_tz
from jarvis.paths import CONFIG_DIR, local_config_path


def load_india_config(config_dir: Path = CONFIG_DIR) -> dict[str, Any]:
    local = _read_yaml(local_config_path(config_dir))
    return _merge(_read_yaml(config_dir / "india.yaml"), local.get("india_file", {}))


def section(cfg: dict[str, Any], name: str) -> dict[str, Any]:
    value = cfg.get(name) or {}
    return value if isinstance(value, dict) else {}


def tz(cfg: dict[str, Any]):
    return get_tz(cfg.get("timezone") or "Asia/Kolkata")
