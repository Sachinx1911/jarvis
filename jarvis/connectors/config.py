"""Load config/connectors.yaml with overrides from config/local.yaml (key: connectors_file)."""

from __future__ import annotations

from datetime import timedelta, timezone, tzinfo
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from jarvis.config import _merge, _read_yaml
from jarvis.paths import local_config_path
from jarvis.paths import CONFIG_DIR

DEFAULT_TZ = "Asia/Kolkata"
# Zones without daylight saving, usable when the IANA database is missing (Windows
# without the tzdata package).
_FIXED = {"Asia/Kolkata": timedelta(hours=5, minutes=30), "Asia/Calcutta": timedelta(hours=5, minutes=30),
          "UTC": timedelta(0)}


def load_connectors_config(config_dir: Path = CONFIG_DIR) -> dict[str, Any]:
    local = _read_yaml(local_config_path(config_dir))
    return _merge(_read_yaml(config_dir / "connectors.yaml"), local.get("connectors_file", {}))


def get_tz(name: str | None) -> tzinfo:
    name = name or DEFAULT_TZ
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        if name in _FIXED:
            return timezone(_FIXED[name], name)
        raise ValueError(f"unknown time zone {name!r} (on Windows install the tzdata package)")
