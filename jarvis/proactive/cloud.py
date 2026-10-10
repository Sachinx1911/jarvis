"""Local override of routing `cloud_allowed` (Telegram `/cloud off|on`).

config/routing.yaml stays the policy. This file only lets Sachin switch cloud AI off
from his phone (and back on) without editing config. `/cloud on` removes the override,
so the phone can never allow more than routing.yaml allows. The file lives in
<JARVIS_HOME>/data/, so it is per machine and never committed. Any module may call
`cloud_override()` or `apply_cloud_override(config)` before routing a call.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import datetime, timezone
from pathlib import Path

from jarvis.config import Config
from jarvis.paths import default_paths

FILE_NAME = "cloud_override.json"


def override_path(home: Path | None = None) -> Path:
    return (home or default_paths().home) / "data" / FILE_NAME


def cloud_override(home: Path | None = None) -> bool | None:
    """False when cloud AI is switched off locally, None when routing.yaml decides.
    An unreadable override file counts as "off": failing closed is the safe side."""
    path = override_path(home)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return False if not isinstance(data, dict) or data.get("cloud_allowed") is not True else None


def set_cloud_override(allowed: bool, source: str = "telegram", home: Path | None = None) -> None:
    """allowed=False switches cloud AI off; True removes the override (routing.yaml decides)."""
    path = override_path(home)
    if allowed:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"cloud_allowed": False, "source": source,
              "set_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    path.write_text(json.dumps(record), encoding="utf-8")


def effective_cloud_allowed(config: Config, home: Path | None = None) -> bool:
    return bool(config.routing.get("cloud_allowed", False)) and cloud_override(home) is None


def apply_cloud_override(config: Config, home: Path | None = None) -> Config:
    """A copy of config with cloud_allowed switched off when the override says so."""
    if cloud_override(home) is None:
        return config
    return dataclasses.replace(config, routing={**config.routing, "cloud_allowed": False})
