"""Settings for memory upkeep: config/memory.yaml + `memory_file:` in config/local.yaml.

Kept apart from jarvis/config.py so the shared Config type does not change.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jarvis.config import _merge, _read_yaml
from jarvis.paths import CONFIG_DIR, local_config_path

DEFAULTS: dict[str, Any] = {
    "core": {"enabled": True, "user_chars": 1375, "memory_chars": 2200, "write_approval": False},
    "quiet_extract": {
        "enabled": True, "every_minutes": 10, "quiet_minutes": 20, "max_age_hours": 24,
        "max_sessions_per_run": 5, "max_failures": 3, "output": "file",
    },
    "cleanup": {
        "enabled": True, "cron": "0 21 * * sun", "output": "telegram", "duplicate_similarity": 0.9,
        "borderline_similarity": 0.75, "archive_after_days": 90, "keep_types": ["constraint", "preference"],
    },
}


def load_memory_settings(config_dir: Path = CONFIG_DIR) -> dict[str, Any]:
    local = _read_yaml(local_config_path(config_dir))
    return _merge(_merge(DEFAULTS, _read_yaml(config_dir / "memory.yaml")), local.get("memory_file", {}) or {})
