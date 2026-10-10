"""Global daily cap and runaway guard for unattended work (schedules and triggers).

From the Hermes masterclass review (PROGRESS.md, 2026-10-10): one runaway loop must not burn
the whole day's model allowance, and a job that keeps failing must stop by itself.

- Usage is read from the run receipts in SQLite (sched_runs and trig_fires), so the cap holds
  across restarts and covers the daemon and the CLI alike.
- A "run" counts toward the cap only when it made at least one model call: a quiet check that
  used no model costs nothing. Trigger fires do not record notional dollars, so only their
  model calls count toward the dollar part.
- A `run-now` that Sachin starts himself is counted but never blocked by the cap.
- A schedule or trigger that fails (or hits its budget) several times in a row is paused and
  Sachin is told. Skipped, missed, stopped and capped runs neither count nor reset the streak.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import Any

FAIL_STATUSES = ("failed", "budget")
SUCCESS_STATUSES = ("ok", "quiet")
CAPPED = "capped"


@dataclass(frozen=True)
class DailyCap:
    max_runs: int | None = None
    max_model_calls: int | None = None
    max_notional_usd: float | None = None

    @classmethod
    def from_settings(cls, sec: dict[str, Any] | None) -> "DailyCap":
        sec = sec or {}

        def num(key: str, kind):
            value = sec.get(key)
            return None if value in (None, "", 0) else kind(value)

        return cls(num("max_runs", int), num("max_model_calls", int), num("max_notional_usd", float))

    def active(self) -> bool:
        return any(v is not None for v in (self.max_runs, self.max_model_calls, self.max_notional_usd))


@dataclass
class Usage:
    runs: int = 0
    model_calls: int = 0
    usd: float = 0.0

    def line(self) -> str:
        return f"{self.runs} runs with model calls, {self.model_calls} model calls, ${self.usd:.2f} notional"


def _day_start(now: datetime) -> datetime:
    return datetime.combine(now.date(), time.min, now.tzinfo)


def _parse(value: str, fallback_tz) -> datetime | None:
    try:
        dt = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=fallback_tz or timezone.utc)


def _rows(conn: sqlite3.Connection, sql: str, args: tuple) -> list[tuple]:
    try:
        return conn.execute(sql, args).fetchall()
    except sqlite3.OperationalError:
        return []  # the table is created on first use of schedules or triggers


def usage_today(conn: sqlite3.Connection, now: datetime) -> Usage:
    start = _day_start(now)
    prefilter = (start - timedelta(days=1)).date().isoformat()  # coarse text filter; exact check below
    u = Usage()
    for started, calls, usd in _rows(conn, "SELECT started_at, model_calls, notional_usd FROM sched_runs "
                                           "WHERE started_at >= ?", (prefilter,)):
        dt = _parse(started, now.tzinfo)
        if dt is None or dt < start:
            continue
        u.model_calls += int(calls or 0)
        u.usd += float(usd or 0.0)
        u.runs += 1 if calls else 0
    for started, calls in _rows(conn, "SELECT started_at, model_calls FROM trig_fires WHERE started_at >= ?",
                                (prefilter,)):
        dt = _parse(started, now.tzinfo)
        if dt is None or dt < start:
            continue
        u.model_calls += int(calls or 0)
        u.runs += 1 if calls else 0
    return u


def capped_today(conn: sqlite3.Connection, now: datetime) -> bool:
    """True when a capped run was already recorded today (so the notice is sent once a day)."""
    start = _day_start(now)
    prefilter = (start - timedelta(days=1)).date().isoformat()
    for table in ("sched_runs", "trig_fires"):
        for (started,) in _rows(conn, f"SELECT started_at FROM {table} WHERE status=? AND started_at >= ?",
                                (CAPPED, prefilter)):
            dt = _parse(started, now.tzinfo)
            if dt is not None and dt >= start:
                return True
    return False


def consecutive_failures(statuses_newest_first: list[str]) -> int:
    n = 0
    for status in statuses_newest_first:
        if status in FAIL_STATUSES:
            n += 1
        elif status in SUCCESS_STATUSES:
            break
    return n


@dataclass
class UnattendedGuard:
    cap: DailyCap
    pause_after_failures: int = 3

    @classmethod
    def from_settings(cls, sec: dict[str, Any] | None) -> "UnattendedGuard":
        sec = sec or {}
        return cls(DailyCap.from_settings(sec.get("daily_cap")), int(sec.get("pause_after_failures") or 0))

    def over_cap(self, conn: sqlite3.Connection, now: datetime) -> str | None:
        if not self.cap.active():
            return None
        u = usage_today(conn, now)
        if self.cap.max_runs is not None and u.runs >= self.cap.max_runs:
            return f"{u.runs} runs with model calls today (cap {self.cap.max_runs})"
        if self.cap.max_model_calls is not None and u.model_calls >= self.cap.max_model_calls:
            return f"{u.model_calls} model calls today (cap {self.cap.max_model_calls})"
        if self.cap.max_notional_usd is not None and u.usd >= self.cap.max_notional_usd:
            return f"${u.usd:.2f} notional today (cap ${self.cap.max_notional_usd:.2f})"
        return None

    def clip(self, limits: dict[str, Any], conn: sqlite3.Connection, now: datetime
             ) -> tuple[int | None, float | None]:
        """The run's own budget, lowered to what is left of today's cap."""
        calls, usd = limits.get("max_model_calls"), limits.get("max_notional_usd")
        if not self.cap.active():
            return calls, usd
        u = usage_today(conn, now)
        if self.cap.max_model_calls is not None:
            left = max(self.cap.max_model_calls - u.model_calls, 0)
            calls = left if calls is None else min(int(calls), left)
        if self.cap.max_notional_usd is not None:
            left_usd = max(self.cap.max_notional_usd - u.usd, 0.0)
            usd = left_usd if usd is None else min(float(usd), left_usd)
        return calls, usd

    def should_pause(self, statuses_newest_first: list[str]) -> bool:
        return self.pause_after_failures > 0 and consecutive_failures(statuses_newest_first) >= self.pause_after_failures


def cap_notice(reason: str) -> str:
    return (f"Daily cap for unattended work reached ({reason}). Scheduled runs and trigger actions that need "
            "the model are paused until tomorrow; reminders and plain notifications still work. "
            "Change the cap in config/local.yaml (proactive_file: unattended: daily_cap).")
