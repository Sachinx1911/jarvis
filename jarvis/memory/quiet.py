"""Memory extraction after a quiet session (PLAN.md 6.3 rule 8).

A chat session whose last message is older than `quiet_minutes` and whose user messages
were not extracted yet is passed to Extractor.extract_session, with Sachin's own messages
only (never Jarvis's replies, tool output or injected memories).

Bookkeeping lives in its own table, mem_extracted_sessions:
- extracted_at / results_json: the last successful extraction.
- upto_message_id: the last message id it covered. If Sachin comes back to the same
  session later, only the newer user messages are extracted the next time.
- failures: extraction calls that failed (provider error or invalid output). The session
  is retried on the next run, and given up after `max_failures`.

`ChatSession.end()` (the /exit path) records its extraction with mark_extracted(), so a
session extracted at /exit is not extracted again here.

Which sessions count as chats: ChatSession ids (12 hex characters). Task and agent runs
use other ids. Unattended schedule turns (prompt and skill schedules) start with the
unattended header and are skipped: those words are not Sachin's.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS mem_extracted_sessions (
    session_id TEXT PRIMARY KEY,
    extracted_at TEXT,
    results_json TEXT NOT NULL DEFAULT '[]',
    upto_message_id INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT '',
    failures INTEGER NOT NULL DEFAULT 0
);
"""

CHAT_SESSION_RE = re.compile(r"^[0-9a-f]{12}$")
UNATTENDED_PREFIX = "[Scheduled run of"   # jarvis.proactive.scheduler.unattended_header
_ERROR_EVENTS = {"extractor_error", "extractor_invalid_output"}


def ensure_table(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


def _db_time(now: datetime) -> str:
    """messages.ts is SQLite datetime('now'): UTC, 'YYYY-MM-DD HH:MM:SS'. A naive `now` is taken as UTC."""
    if now.tzinfo is not None:
        now = now.astimezone(timezone.utc).replace(tzinfo=None)
    return now.strftime("%Y-%m-%d %H:%M:%S")


def _text_of(parts_json: str) -> str:
    try:
        parts = json.loads(parts_json)
    except (TypeError, ValueError):
        return ""
    return "".join(p.get("text", "") for p in parts if isinstance(p, dict) and p.get("type") == "TextPart")


def _last_message_id(conn: sqlite3.Connection, session_id: str) -> int:
    row = conn.execute("SELECT MAX(id) FROM messages WHERE session_id=?", (session_id,)).fetchone()
    return int(row[0] or 0)


def mark_extracted(conn: sqlite3.Connection, session_id: str, results: list[Any] | None,
                   now: datetime | None = None, source: str = "end") -> None:
    """Record that this session's user messages (up to now) were extracted.

    Called by the quiet job, and by ChatSession.end() so /exit and the job never extract
    the same messages twice.
    """
    ensure_table(conn)
    when = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    upto = _last_message_id(conn, session_id)
    conn.execute(
        """INSERT INTO mem_extracted_sessions (session_id, extracted_at, results_json, upto_message_id, source, failures)
           VALUES (?, ?, ?, ?, ?, 0)
           ON CONFLICT(session_id) DO UPDATE SET extracted_at=excluded.extracted_at,
               results_json=excluded.results_json, upto_message_id=excluded.upto_message_id,
               source=excluded.source, failures=0""",
        (session_id, when, json.dumps([list(r) for r in (results or [])], ensure_ascii=False), upto, source))
    conn.commit()
    # Fact-augmented session search: index the saved facts next to this session's chat text.
    # An index failure must never undo or block the extraction record above.
    from jarvis.memory.session_facts import index_session

    try:
        index_session(conn, session_id, results or [])
    except (sqlite3.Error, OSError, ValueError):
        pass


def _mark_failed(conn: sqlite3.Connection, session_id: str) -> int:
    conn.execute(
        """INSERT INTO mem_extracted_sessions (session_id, failures) VALUES (?, 1)
           ON CONFLICT(session_id) DO UPDATE SET failures=failures + 1""", (session_id,))
    conn.commit()
    return int(conn.execute("SELECT failures FROM mem_extracted_sessions WHERE session_id=?",
                            (session_id,)).fetchone()[0])


def extraction_record(conn: sqlite3.Connection, session_id: str) -> dict[str, Any] | None:
    ensure_table(conn)
    row = conn.execute(
        """SELECT session_id, extracted_at, results_json, upto_message_id, source, failures
           FROM mem_extracted_sessions WHERE session_id=?""", (session_id,)).fetchone()
    if not row:
        return None
    keys = ("session_id", "extracted_at", "results", "upto_message_id", "source", "failures")
    data = dict(zip(keys, row))
    data["results"] = json.loads(data["results"] or "[]")
    return data


def is_extracted(conn: sqlite3.Connection, session_id: str) -> bool:
    rec = extraction_record(conn, session_id)
    return bool(rec and rec["extracted_at"])


def unextracted_user_messages(conn: sqlite3.Connection, session_id: str) -> list[str]:
    """Sachin's messages in this session that no extraction has covered yet, oldest first."""
    rec = extraction_record(conn, session_id)
    upto = rec["upto_message_id"] if rec else 0
    rows = conn.execute("SELECT parts FROM messages WHERE session_id=? AND role='user' AND id>? ORDER BY id",
                        (session_id, upto)).fetchall()
    return [t for t in (_text_of(r[0]) for r in rows) if t.strip()]


def quiet_sessions(conn: sqlite3.Connection, now: datetime, quiet_minutes: float = 20,
                   max_age_hours: float = 24, max_failures: int = 3) -> list[str]:
    """Chat sessions that went quiet and have user messages no extraction has covered, oldest first."""
    ensure_table(conn)
    cutoff = _db_time(now - timedelta(minutes=quiet_minutes))
    oldest = _db_time(now - timedelta(hours=max_age_hours))
    rows = conn.execute(
        """SELECT m.session_id, MAX(m.ts) AS last_ts,
                  MAX(CASE WHEN m.role='user' THEN m.id END) AS last_user_id,
                  COALESCE(e.upto_message_id, 0), COALESCE(e.failures, 0)
           FROM messages m LEFT JOIN mem_extracted_sessions e ON e.session_id = m.session_id
           GROUP BY m.session_id
           HAVING last_ts <= ? AND last_ts >= ? AND last_user_id IS NOT NULL
           ORDER BY last_ts""", (cutoff, oldest)).fetchall()
    out = []
    for sid, _last_ts, last_user_id, upto, failures in rows:
        if not CHAT_SESSION_RE.match(sid or "") or last_user_id <= upto or failures >= max_failures:
            continue
        first = conn.execute("SELECT parts FROM messages WHERE session_id=? AND role='user' ORDER BY id LIMIT 1",
                             (sid,)).fetchone()
        if first and _text_of(first[0]).lstrip().startswith(UNATTENDED_PREFIX):
            continue  # a schedule's unattended turn, not Sachin talking
        out.append(sid)
    return out


class _AuditWatch:
    """Wraps the extractor's audit log to see whether the model call failed (the extractor
    returns [] for both "nothing worth saving" and "the call failed")."""

    def __init__(self, inner: Any):
        self.inner = inner
        self.events: list[str] = []

    def write(self, event: str, **fields: Any) -> Any:
        self.events.append(event)
        return self.inner.write(event, **fields) if self.inner is not None else None

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)


@dataclass
class SessionOutcome:
    session_id: str
    status: str                       # extracted | failed | gave_up | no_text
    results: list[tuple[str, str]] = field(default_factory=list)

    @property
    def saved(self) -> list[str]:
        return [mid for action, mid in self.results if action in ("ADD", "UPDATE", "SUPERSEDE")]


@dataclass
class QuietRun:
    outcomes: list[SessionOutcome] = field(default_factory=list)
    skipped_reason: str = ""

    @property
    def saved(self) -> list[str]:
        return [mid for o in self.outcomes for mid in o.saved]

    def summary(self) -> str:
        if self.skipped_reason:
            return f"Memory extraction skipped: {self.skipped_reason}."
        lines = [f"Memory extraction after quiet sessions: {len(self.outcomes)} session(s), "
                 f"{len(self.saved)} memory change(s)."]
        for o in self.outcomes:
            detail = ", ".join(f"{a} {m}" for a, m in o.results) or "nothing to save"
            lines.append(f"- {o.session_id}: {o.status} ({detail})")
        return "\n".join(lines)


def extract_quiet_sessions(conn: sqlite3.Connection, extractor: Any, now: datetime, quiet_minutes: float = 20,
                           max_age_hours: float = 24, max_sessions: int = 5, max_failures: int = 3,
                           audit: Any = None) -> QuietRun:
    """One pass of the quiet-session job. `extractor` is a jarvis.memory.extract.Extractor."""
    if audit is None:
        audit = getattr(extractor, "audit", None)
    if extractor is None or getattr(extractor, "provider", None) is None:
        if audit:
            audit.write("quiet_extract_skipped", reason="no model route for the memory extractor")
        return QuietRun(skipped_reason="no model route for the memory extractor")
    run = QuietRun()
    for sid in quiet_sessions(conn, now, quiet_minutes, max_age_hours, max_failures)[:max_sessions]:
        msgs = unextracted_user_messages(conn, sid)
        if not msgs:
            mark_extracted(conn, sid, [], now, source="quiet")
            run.outcomes.append(SessionOutcome(sid, "no_text"))
            continue
        watch = _AuditWatch(extractor.audit)
        extractor.audit = watch
        try:
            results = extractor.extract_session(msgs)
        finally:
            extractor.audit = watch.inner
        if not results and _ERROR_EVENTS & set(watch.events):
            failures = _mark_failed(conn, sid)
            status = "gave_up" if failures >= max_failures else "failed"
            run.outcomes.append(SessionOutcome(sid, status))
            if audit:
                audit.write("quiet_extract_failed", session_id=sid, failures=failures, gave_up=status == "gave_up")
            continue
        mark_extracted(conn, sid, results, now, source="quiet")
        run.outcomes.append(SessionOutcome(sid, "extracted", [tuple(r) for r in results]))  # type: ignore[misc]
        if audit:
            audit.write("session_extracted", session_id=sid, results=results, how="quiet", messages=len(msgs))
    return run
