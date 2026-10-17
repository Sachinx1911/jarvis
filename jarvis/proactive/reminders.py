"""One-off reminders: "remind me in 10 minutes ...", "udya sakali 9 la ... aathvan kar".

Stored in SQLite (table reminder_items), so they survive restarts. The daemon checks for
due reminders every few seconds and sends them through the notifier. A reminder that came
due while Jarvis was off is sent late, marked as late, rather than dropped. Reminders use
no model and no tool, so they still arrive while the emergency stop is on.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime

from jarvis.control.audit import AuditLog
from jarvis.proactive.timeparse import parse_once

_SCHEMA = """
CREATE TABLE IF NOT EXISTS reminder_items (
    id INTEGER PRIMARY KEY,
    text TEXT NOT NULL,
    due_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',   -- pending | sent | cancelled | failed
    created_at TEXT NOT NULL,
    sent_at TEXT,
    channel TEXT,
    source TEXT,
    workspace TEXT NOT NULL DEFAULT 'personal'
);
CREATE INDEX IF NOT EXISTS reminder_due ON reminder_items(status, due_at);
"""

_LEAD = re.compile(
    r"^\s*(please\s+)?(remind\s+me|reminder|set\s+a\s+reminder|jarvis,?)\s*(to|that|about|:)?\s*", re.IGNORECASE)
# Marathi endings: "... aathvan kar", "... athvan karun de", "... आठवण कर".
_TAIL = re.compile(r"(^|\s+)(aathvan|aathavan|athvan|athavan|aatvan|आठवण)\s*(kar|karun\s+de|करून\s+दे|कर)?"
                   r"\s*[.!]?\s*$", re.IGNORECASE)
LATE_AFTER_SECONDS = 120


@dataclass
class Reminder:
    id: int
    text: str
    due_at: datetime
    status: str
    sent_at: str | None = None


def clean_text(rest: str) -> str:
    text = _LEAD.sub("", rest.strip())
    text = _TAIL.sub("", text).strip(" ,.;:-")
    return text


class ReminderStore:
    def __init__(self, conn: sqlite3.Connection, audit: AuditLog | None = None):
        self.db = conn
        self.audit = audit
        self.db.executescript(_SCHEMA)
        if "workspace" not in {r[1] for r in self.db.execute("PRAGMA table_info(reminder_items)")}:
            try:
                self.db.execute("ALTER TABLE reminder_items ADD COLUMN workspace TEXT NOT NULL DEFAULT 'personal'")
            except sqlite3.OperationalError as e:
                if "duplicate column" not in str(e).lower():
                    raise
            self.db.commit()

    def add(self, text: str, due: datetime, source: str = "cli", now: datetime | None = None,
            workspace: str = "personal") -> Reminder:
        if due.tzinfo is None:
            raise ValueError("due time needs a timezone")
        created = (now or datetime.now(due.tzinfo)).isoformat(timespec="seconds")
        cur = self.db.execute(
            "INSERT INTO reminder_items (text, due_at, created_at, source, workspace) VALUES (?, ?, ?, ?, ?)",
            (text, due.isoformat(timespec="seconds"), created, source, workspace or "personal"))
        self.db.commit()
        if self.audit:
            self.audit.write("reminder_added", reminder_id=cur.lastrowid, due_at=due.isoformat(), source=source)
        return self.get(cur.lastrowid)  # type: ignore[arg-type,return-value]

    def get(self, rid: int) -> Reminder | None:
        row = self.db.execute("SELECT id, text, due_at, status, sent_at FROM reminder_items WHERE id=?",
                              (rid,)).fetchone()
        return _row(row) if row else None

    def pending(self) -> list[Reminder]:
        rows = self.db.execute("SELECT id, text, due_at, status, sent_at FROM reminder_items "
                               "WHERE status='pending' ORDER BY due_at").fetchall()
        return [_row(r) for r in rows]

    def upcoming(self, start: datetime, end: datetime) -> list[Reminder]:
        return [r for r in self.pending() if start <= r.due_at < end]

    def due(self, now: datetime) -> list[Reminder]:
        return [r for r in self.pending() if r.due_at <= now]

    def cancel(self, rid: int) -> bool:
        cur = self.db.execute("UPDATE reminder_items SET status='cancelled' WHERE id=? AND status='pending'", (rid,))
        self.db.commit()
        return cur.rowcount == 1

    def _mark(self, rid: int, status: str, now: datetime, channel: str | None) -> bool:
        # Only one process may send a reminder: the status flip is the lock.
        cur = self.db.execute("UPDATE reminder_items SET status=?, sent_at=?, channel=? WHERE id=? AND status='pending'",
                              (status, now.isoformat(timespec="seconds"), channel, rid))
        self.db.commit()
        return cur.rowcount == 1

    def fire_due(self, now: datetime, notifier) -> list[Reminder]:
        """Send every due reminder once. Returns what was sent."""
        sent = []
        for r in self.due(now):
            if not self._mark(r.id, "sending", now, None):
                continue  # another process took it
            late = (now - r.due_at).total_seconds() > LATE_AFTER_SECONDS
            when = r.due_at.strftime("%H:%M")
            text = f"Reminder: {r.text}" + (f"\n(late: it was due at {when} on {r.due_at:%d %b})" if late else "")
            try:
                channel = notifier.send(text, "Reminder")
            except Exception as e:  # noqa: BLE001 - keep it for the next check
                self.db.execute("UPDATE reminder_items SET status='pending' WHERE id=?", (r.id,))
                self.db.commit()
                if self.audit:
                    self.audit.write("reminder_send_failed", reminder_id=r.id, detail=str(e))
                continue
            self.db.execute("UPDATE reminder_items SET status='sent', channel=? WHERE id=?",
                            (channel if isinstance(channel, str) else None, r.id))
            self.db.commit()
            if self.audit:
                self.audit.write("reminder_sent", reminder_id=r.id, late=late)
            sent.append(r)
        return sent


def _row(row) -> Reminder:
    return Reminder(row[0], row[1], datetime.fromisoformat(row[2]), row[3], row[4])


@dataclass
class ParsedReminder:
    text: str
    due: datetime


def parse_reminder(text: str, now: datetime) -> ParsedReminder | None:
    """None when the time is unclear: Jarvis then asks instead of guessing."""
    found = parse_once(text, now)
    if not found:
        return None
    message = clean_text(found.rest)
    if not message:
        return None
    return ParsedReminder(message, found.due)
