"""Safe edits of config/local.yaml from the dashboard.

Only a fixed set of keys can be written (an allowlist, never a free path). The file is
read, merged and written atomically (temp file + replace) with a one-step backup
(local.yaml.bak). A file that is not a YAML mapping is never overwritten. Comments in
local.yaml are not kept by the YAML writer; the backup keeps the previous text.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import yaml

from jarvis.config import _merge, _read_yaml

LOCAL_FILE = "local.yaml"

# dashboard field -> list of key paths inside config/local.yaml that receive the value
FIELDS: dict[str, list[tuple[str, ...]]] = {
    "telegram_allowed_user_id": [("proactive_file", "telegram", "allowed_user_id")],
    # The chat weather tool (config/tools.yaml) and the morning brief (config/proactive.yaml)
    # each read their own default place; the dashboard sets both.
    "weather_place": [("tools_file", "weather", "default_place"), ("proactive_file", "brief", "place")],
}

# Fields other tabs write (the Setup tab neither shows nor sends them).
EXTRA_FIELDS: dict[str, list[tuple[str, ...]]] = {
    # India tab: the mutual fund schemes whose NAVs are shown, [{code, label}] (jarvis/india/nav.py).
    "india_nav_schemes": [("india_file", "nav", "schemes")],
}


class LocalConfigError(ValueError):
    pass


def _get(data: dict[str, Any], path: tuple[str, ...]) -> Any:
    cur: Any = data
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            return None
        cur = cur[key]
    return cur


def read_local(config_dir: Path) -> dict[str, Any]:
    try:
        return _read_yaml(config_dir / LOCAL_FILE)
    except (ValueError, yaml.YAMLError) as e:
        raise LocalConfigError(f"config/local.yaml cannot be read: {e}") from e


def current_values(config_dir: Path) -> dict[str, Any]:
    """The dashboard fields as set in local.yaml (falls back to the shared config files)."""
    local = read_local(config_dir)
    shared = {
        ("proactive_file",): _read_yaml(config_dir / "proactive.yaml"),
        ("tools_file",): _read_yaml(config_dir / "tools.yaml"),
    }
    out: dict[str, Any] = {}
    for field, paths in FIELDS.items():
        value = _get(local, paths[0])
        if value in (None, ""):
            base = shared.get(paths[0][:1], {})
            value = _get(base, paths[0][1:])
        out[field] = value if value not in ("",) else None
    return out


def update_local(config_dir: Path, values: dict[str, Any]) -> list[str]:
    """Merge the given dashboard fields into local.yaml. Returns the key paths changed."""
    writable = {**FIELDS, **EXTRA_FIELDS}
    unknown = set(values) - set(writable)
    if unknown:
        raise LocalConfigError(f"cannot set: {', '.join(sorted(unknown))}")
    path = config_dir / LOCAL_FILE
    data = read_local(config_dir)
    patch: dict[str, Any] = {}
    changed: list[str] = []
    for field, value in values.items():
        for keys in writable[field]:
            node = patch
            for key in keys[:-1]:
                node = node.setdefault(key, {})
            node[keys[-1]] = value
            if _get(data, keys) != value:
                changed.append(".".join(keys))
    if not changed:
        return []
    merged = _merge(data, patch)
    text = ("# Machine-specific settings (git-ignored). Written by the Jarvis dashboard; edit freely.\n"
            + yaml.safe_dump(merged, sort_keys=False, allow_unicode=True))
    config_dir.mkdir(parents=True, exist_ok=True)
    if path.exists():
        (config_dir / (LOCAL_FILE + ".bak")).write_bytes(path.read_bytes())
    fd, tmp = tempfile.mkstemp(prefix=".local-", suffix=".yaml", dir=config_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return changed
