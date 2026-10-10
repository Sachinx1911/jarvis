"""Dashboard data from the other phases (wired by the lead; see adapters.HOOKS).

Read-only, no model calls, nothing secret: these run inside a dashboard request.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from jarvis.paths import default_paths


def _home(home: Path | None) -> Path:
    return home or default_paths().home


def _conn(home: Path) -> sqlite3.Connection:
    return sqlite3.connect(home / "data" / "jarvis.db")


def schedules(home: Path | None = None) -> dict[str, Any]:
    from jarvis.proactive.scheduler import ScheduleStore

    conn = _conn(_home(home))
    try:
        items = [{"id": s.id, "what": f"{s.kind}: {s.name}", "when": f"{s.cron} ({s.timezone})",
                  "enabled": s.enabled, "last_run": s.last_run_at, "next_run": s.next_run_at,
                  "last_status": s.last_status} for s in ScheduleStore(conn).list()]
    finally:
        conn.close()
    return {"items": items}


def telegram(home: Path | None = None) -> dict[str, Any]:
    from jarvis.proactive.settings import load_settings
    from jarvis.secrets import get_secret

    tg = load_settings().section("telegram")
    return {"token_set": bool(get_secret("telegram_bot_token")),
            "allowed_user_set": bool(tg.get("allowed_user_id")),
            "detail": "run `jarvis daemon` to start the bot and the scheduler"}


def connectors(home: Path | None = None) -> dict[str, Any]:
    from jarvis.connectors.registry import ConnectorDeps, connector_health
    from jarvis.control.audit import AuditLog
    from jarvis.db import Store

    h = _home(home)
    store = Store(h / "data" / "jarvis.db")
    try:
        rows = connector_health(ConnectorDeps(h, store, AuditLog(h / "data" / "audit.jsonl")))
    finally:
        store.close()
    return {"items": [{"name": n, "type": "connector", "enabled": True, "health": "ok" if ok else "not ok",
                       "detail": d} for n, ok, d in rows]}


def documents(home: Path | None = None) -> dict[str, Any]:
    from jarvis.connectors.registry import ConnectorDeps, doc_library
    from jarvis.control.audit import AuditLog
    from jarvis.db import Store

    h = _home(home)
    store = Store(h / "data" / "jarvis.db")
    try:
        docs = doc_library(ConnectorDeps(h, store, AuditLog(h / "data" / "audit.jsonl"))).documents()
    finally:
        store.close()
    return {"count": len(docs), "items": [{"id": f"{d.project}/{d.file}", "title": d.file, "class": d.privacy,
                                           "project": d.project, "chunks": d.chunks, "status": d.status} for d in docs]}


def voice(home: Path | None = None) -> dict[str, Any]:
    import importlib.util

    from jarvis.voice.config import load_voice_config

    cfg = load_voice_config()
    return {"stt_installed": importlib.util.find_spec("faster_whisper") is not None,
            "recorder_installed": importlib.util.find_spec("sounddevice") is not None,
            "marathi_cloud_voice": bool(((cfg.get("tts") or {}).get("marathi") or {}).get("cloud_enabled")),
            "wake_word": bool((cfg.get("wake_word") or {}).get("enabled"))}


def cloud(home: Path | None = None) -> dict[str, Any]:
    from jarvis.config import load_config
    from jarvis.proactive.cloud import cloud_override, effective_cloud_allowed

    h = _home(home)
    return {"cloud_allowed": effective_cloud_allowed(load_config(), h),
            "source": "file" if cloud_override(h) is not None else "config"}
