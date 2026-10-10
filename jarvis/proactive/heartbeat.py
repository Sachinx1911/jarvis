"""Heartbeat (PLAN.md 12, OpenClaw's design): every 30 minutes, read HEARTBEAT.md and decide
whether anything is worth telling Sachin.

Cheap by design:
- an empty checklist, quiet hours, or the emergency stop mean no model call at all;
- the facts (tasks, schedules, approvals, reminders) are gathered without a model;
- one small structured call decides, and the same message is not repeated within
  `repeat_after_hours`.
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from jarvis.control.audit import AuditLog
from jarvis.control.stop import StopSwitch
from jarvis.paths import PROMPTS_DIR
from jarvis.privacy import redact_p3
from jarvis.proactive.settings import ProactiveSettings
from jarvis.providers.base import LLMRequest, Message, ProviderError, ReasoningProvider
from jarvis.routing.policy import RouteDecision
from jarvis.schema import validate

ROUTE = "heartbeat"
FILE_NAME = "HEARTBEAT.md"

DECIDE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"speak": {"type": "boolean"}, "message": {"type": "string"}, "reason": {"type": "string"}},
    "required": ["speak", "message", "reason"],
    "additionalProperties": False,
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sched_heartbeat (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    spoke INTEGER NOT NULL,
    reason TEXT,
    message TEXT,
    msg_hash TEXT,
    model_called INTEGER NOT NULL DEFAULT 0
);
"""


@dataclass
class HeartbeatResult:
    spoke: bool
    message: str
    reason: str
    model_called: bool = False


def heartbeat_path(home: Path) -> Path:
    return home / "profile" / FILE_NAME


def ensure_checklist(home: Path) -> Path:
    path = heartbeat_path(home)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text((PROMPTS_DIR / "heartbeat_template.md").read_text(encoding="utf-8"), encoding="utf-8")
    return path


def read_checklist(home: Path) -> list[str]:
    items = []
    for line in ensure_checklist(home).read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s.startswith(("- ", "* ")) and len(s) > 2:
            items.append(s[2:].strip())
    return items


def _hash(text: str) -> str:
    return hashlib.sha256(" ".join(text.lower().split()).encode()).hexdigest()[:16]


def gather_facts(conn: sqlite3.Connection, now: datetime) -> list[str]:
    """What Jarvis knows right now, without a model. Missing tables just mean "nothing yet"."""
    facts = [f"Local time: {now:%A %d %B %Y, %H:%M}"]

    def rows(sql: str, args: tuple = ()) -> list[tuple]:
        try:
            return conn.execute(sql, args).fetchall()
        except sqlite3.OperationalError:
            return []

    for tid, title, state, err in rows(
            "SELECT id, title, state, last_error FROM tasks WHERE state IN ('FAILED','WAITING_APPROVAL','PAUSED') "
            "ORDER BY updated_at DESC LIMIT 10"):
        facts.append(f"Task {tid} '{title}' is {state}" + (f" (error: {err})" if err else ""))
    n_open = rows("SELECT COUNT(*) FROM tasks WHERE state NOT IN ('COMPLETED','FAILED','CANCELLED')")
    if n_open and n_open[0][0]:
        facts.append(f"Open tasks: {n_open[0][0]}")
    for sid, name, status, when in rows(
            "SELECT id, name, last_status, last_run_at FROM sched_schedules "
            "WHERE last_status IN ('failed','missed','budget','stopped') AND enabled=1"):
        facts.append(f"Schedule {sid} '{name}' last run: {status} at {when}")
    pend = rows("SELECT COUNT(*) FROM sched_pending_approvals WHERE status='pending'")
    if pend and pend[0][0]:
        facts.append(f"Actions from unattended runs waiting for approval: {pend[0][0]}")
    soon = (now + timedelta(hours=2)).isoformat(timespec="seconds")
    for text, due in rows("SELECT text, due_at FROM reminder_items WHERE status='pending' AND due_at <= ? "
                          "ORDER BY due_at LIMIT 5", (soon,)):
        facts.append(f"Reminder due {due[11:16]}: {text}")
    return facts


class Heartbeat:
    def __init__(self, home: Path, settings: ProactiveSettings, conn: sqlite3.Connection, audit: AuditLog,
                 provider: ReasoningProvider | None, decision: RouteDecision | None, store=None):
        self.home = home
        self.settings = settings
        self.db = conn
        self.audit = audit
        self.provider = provider
        self.decision = decision
        self.store = store  # jarvis.db.Store, for usage records
        self.db.executescript(_SCHEMA)

    def _log(self, now: datetime, result: HeartbeatResult) -> HeartbeatResult:
        self.db.execute(
            "INSERT INTO sched_heartbeat (ts, spoke, reason, message, msg_hash, model_called) VALUES (?, ?, ?, ?, ?, ?)",
            (now.isoformat(timespec="seconds"), int(result.spoke), result.reason, result.message,
             _hash(result.message) if result.message else None, int(result.model_called)))
        self.db.commit()
        self.audit.write("heartbeat", spoke=result.spoke, reason=result.reason, model_called=result.model_called)
        return result

    def recently_said(self, now: datetime) -> list[str]:
        hours = float(self.settings.section("heartbeat").get("repeat_after_hours", 6))
        since = (now - timedelta(hours=hours)).isoformat(timespec="seconds")
        return [r[0] for r in self.db.execute(
            "SELECT message FROM sched_heartbeat WHERE spoke=1 AND ts >= ? ORDER BY id", (since,))]

    def run(self, now: datetime) -> HeartbeatResult:
        items = read_checklist(self.home)
        if not items:
            return self._log(now, HeartbeatResult(False, "", "checklist is empty"))
        if StopSwitch(self.home / "data").engaged():
            return self._log(now, HeartbeatResult(False, "", "emergency stop is on"))
        if self.settings.in_quiet_hours(now):
            return self._log(now, HeartbeatResult(False, "", "quiet hours"))
        if not self.provider or not self.decision:
            return self._log(now, HeartbeatResult(False, "", "no model route available"))

        recent = self.recently_said(now)
        facts = gather_facts(self.db, now)
        body = ("Checklist:\n" + "\n".join(f"- {i}" for i in items) + "\n\nFacts:\n" + "\n".join(f"- {f}" for f in facts)
                + "\n\nRecently said:\n" + ("\n".join(f"- {m}" for m in recent) or "- nothing"))
        body, _ = redact_p3(body)
        req = LLMRequest(route=ROUTE, model=self.decision.model,
                         system=(PROMPTS_DIR / "heartbeat.md").read_text(encoding="utf-8"),
                         messages=[Message.text("user", body)], response_schema=DECIDE_SCHEMA,
                         reasoning=self.decision.effort,  # type: ignore[arg-type]
                         privacy_classes=frozenset({"P1"}), max_output=800)
        try:
            res = self.provider.structured(req, DECIDE_SCHEMA)
        except (ProviderError, NotImplementedError) as e:
            return self._log(now, HeartbeatResult(False, "", f"model error: {e}", True))
        if self.store is not None:
            self.store.record_usage(None, ROUTE, res.response)
        if not res.valid or not validate(res.data, DECIDE_SCHEMA):
            return self._log(now, HeartbeatResult(False, "", "model answer was not valid", True))
        data = res.data
        message = data["message"].strip()
        if not data["speak"] or not message:
            return self._log(now, HeartbeatResult(False, "", data["reason"] or "nothing worth saying", True))
        if _hash(message) in {_hash(m) for m in recent}:
            return self._log(now, HeartbeatResult(False, "", "already said recently", True))
        return self._log(now, HeartbeatResult(True, message, data["reason"], True))
