"""Kubera: per-loka (workspace) daily budgets (PLAN.md 27.4, 27.6 item 6).

Budgets existed per task (jarvis/tasks/budget.py) and per day for all unattended work
(jarvis/proactive/guard.py). This adds the third ration: what one office may spend in one day.
The caps come from the workspace's own file (`workspace.yaml`, `budget:` with `max_runs`,
`max_model_calls`, `max_notional_usd`); a missing cap means no cap for that measure. The global
daily cap still applies on top: this never widens it.

Where the numbers come from (read, never written here):
- model calls and notional USD: `model_usage` rows for the workspace since the start of today
  (every model call is recorded there with its workspace since schema v4);
- runs: tasks created today in the workspace (`tasks`) plus schedule runs started today whose
  schedule belongs to the workspace (`sched_runs` joined with `sched_schedules`), counting a
  schedule run only when it made a model call, as the global cap does.

Three enforcement points, each a small function the caller wires:
- `allow_unattended(conn, workspace, budget)`: before an unattended run for that office;
- `LokaMeter`: a callback for `BudgetTracker` so a running task stops with "loka budget: ..."
  on the same path as its own per-task budget (loaded once from the database, then counted in
  memory: the tracker is called from worker threads and SQLite connections are per thread);
- `summary(conn, workspace, budget)`: used versus cap, for `jarvis workspace show`.
`notify_capped` sends the notice once per day per workspace (same pattern as the global cap).
"""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import Any, Callable

from jarvis.workspaces.model import Budget, Workspace

_SCHEMA = """
CREATE TABLE IF NOT EXISTS loka_cap_notices (
    workspace TEXT NOT NULL,
    day TEXT NOT NULL,
    ts TEXT NOT NULL,
    reason TEXT NOT NULL,
    PRIMARY KEY (workspace, day)
);
"""


@dataclass
class LokaUsage:
    runs: int = 0
    model_calls: int = 0
    usd: float = 0.0

    def line(self) -> str:
        return f"{self.runs} runs, {self.model_calls} model calls, ${self.usd:.2f} notional today"


def _budget_of(cfg: Any) -> Budget:
    if isinstance(cfg, Workspace):
        return cfg.budget
    if isinstance(cfg, Budget):
        return cfg
    if cfg is None:
        return Budget()
    if isinstance(cfg, dict):  # the raw `budget:` mapping of a workspace file
        def num(key: str, kind):
            value = cfg.get(key)
            return None if value in (None, "", 0) else kind(value)
        return Budget(num("max_runs", int), num("max_model_calls", int), num("max_notional_usd", float))
    raise TypeError(f"not a workspace budget: {cfg!r}")


def active(budget: Budget) -> bool:
    return any(v is not None for v in (budget.max_runs, budget.max_model_calls, budget.max_notional_usd))


# ---- time windows ----

def _now(now: datetime | None) -> datetime:
    return now if now is not None else datetime.now().astimezone()


def _day_start(now: datetime) -> datetime:
    return datetime.combine(now.date(), time.min, now.tzinfo)


def _utc_text(dt: datetime) -> str:
    """The form SQLite's datetime('now') writes (UTC, no zone), so text comparison is exact."""
    if dt.tzinfo is None:
        dt = dt.astimezone()
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


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
        return []  # a table that is created on first use (schedules) may not exist yet


# ---- counting ----

def usage_today(conn: sqlite3.Connection, workspace: str, now: datetime | None = None) -> LokaUsage:
    now = _now(now)
    start = _day_start(now)
    since = _utc_text(start)
    u = LokaUsage()
    row = _rows(conn, "SELECT COUNT(*), COALESCE(SUM(notional_usd), 0) FROM model_usage "
                      "WHERE workspace = ? AND ts >= ?", (workspace, since))
    if row:
        u.model_calls = int(row[0][0] or 0)
        u.usd = float(row[0][1] or 0.0)
    row = _rows(conn, "SELECT COUNT(*) FROM tasks WHERE workspace = ? AND created_at >= ?", (workspace, since))
    if row:
        u.runs += int(row[0][0] or 0)
    prefilter = (start - timedelta(days=1)).date().isoformat()  # coarse text filter; exact check below
    for started, calls in _rows(conn, "SELECT r.started_at, r.model_calls FROM sched_runs r "
                                      "JOIN sched_schedules s ON s.id = r.schedule_id "
                                      "WHERE s.workspace = ? AND r.started_at >= ?", (workspace, prefilter)):
        dt = _parse(started, now.tzinfo)
        if dt is None or dt < start:
            continue
        u.runs += 1 if calls else 0
    return u


def over(usage: LokaUsage, budget: Budget, workspace: str) -> str | None:
    """Why the office is over its cap today, or None."""
    if budget.max_runs is not None and usage.runs >= budget.max_runs:
        return f"loka budget: {workspace} made {usage.runs} runs today (cap {budget.max_runs})"
    if budget.max_model_calls is not None and usage.model_calls >= budget.max_model_calls:
        return f"loka budget: {workspace} made {usage.model_calls} model calls today (cap {budget.max_model_calls})"
    if budget.max_notional_usd is not None and usage.usd >= budget.max_notional_usd:
        return f"loka budget: {workspace} spent ${usage.usd:.2f} notional today (cap ${budget.max_notional_usd:.2f})"
    return None


def check(conn: sqlite3.Connection, workspace: str, cfg: Any, now: datetime | None = None) -> str | None:
    """None when the office may spend; otherwise the reason it may not. `cfg` is the Workspace,
    its Budget, or the raw `budget:` mapping; missing caps are no caps."""
    budget = _budget_of(cfg)
    if not active(budget):
        return None
    return over(usage_today(conn, workspace, now), budget, workspace)


def allow_unattended(conn: sqlite3.Connection, workspace: str, cfg: Any, now: datetime | None = None) -> str | None:
    """Before an unattended run (schedule, trigger, proactive task) for this office: None = go,
    else the reason to record the run as capped. A run Sachin starts himself is never blocked;
    the caller decides that, as the global cap does."""
    return check(conn, workspace, cfg, now)


def summary(conn: sqlite3.Connection, workspace: str, cfg: Any = None, now: datetime | None = None) -> dict[str, Any]:
    """Used versus cap for `jarvis workspace show` and the dashboard."""
    budget = _budget_of(cfg)
    u = usage_today(conn, workspace, now)
    caps = {"runs": budget.max_runs, "model_calls": budget.max_model_calls, "notional_usd": budget.max_notional_usd}
    used = {"runs": u.runs, "model_calls": u.model_calls, "notional_usd": round(u.usd, 4)}
    return {"workspace": workspace, "used": used, "caps": caps, "over": over(u, budget, workspace) if active(budget) else None,
            "line": summary_line(u, budget)}


def summary_line(u: LokaUsage, budget: Budget) -> str:
    def part(label: str, value, cap) -> str:
        shown = f"${value:.2f}" if label == "notional" else str(value)
        if cap is None:
            return f"{shown} {label}"
        cap_shown = f"${cap:.2f}" if label == "notional" else str(cap)
        return f"{shown}/{cap_shown} {label}"
    return "today: " + ", ".join([part("runs", u.runs, budget.max_runs),
                                  part("model calls", u.model_calls, budget.max_model_calls),
                                  part("notional", u.usd, budget.max_notional_usd)])


# ---- the running-task meter (BudgetTracker callback) ----

class LokaMeter:
    """Counts an office's spend for a running task on top of what the database already holds
    today. Loaded once; afterwards `charge` adds in memory (thread-safe), so it works from
    worker threads without touching SQLite. Use: `BudgetTracker(budget, extra=meter.charge)`."""

    def __init__(self, conn: sqlite3.Connection, workspace: str, cfg: Any, now: datetime | None = None):
        self.workspace = workspace
        self.budget = _budget_of(cfg)
        self.usage = usage_today(conn, workspace, now) if active(self.budget) else LokaUsage()
        self._lock = threading.Lock()

    def charge(self, calls: int = 1, usd: float = 0.0) -> str | None:
        """Add one model call; the reason to stop, or None."""
        if not active(self.budget):
            return None
        with self._lock:
            self.usage.model_calls += calls
            self.usage.usd += usd
            return over(self.usage, self.budget, self.workspace)


# ---- once-a-day notice ----

def notify_capped(conn: sqlite3.Connection, workspace: str, reason: str, notifier: Any,
                  now: datetime | None = None, audit: Any = None) -> bool:
    """Tell Sachin once per day per office that its cap is reached. True when the notice was
    sent now; False when today's notice went out earlier (or there is no notifier)."""
    now = _now(now)
    conn.executescript(_SCHEMA)
    cur = conn.execute("INSERT OR IGNORE INTO loka_cap_notices (workspace, day, ts, reason) VALUES (?, ?, ?, ?)",
                       (workspace, now.date().isoformat(), now.isoformat(timespec="seconds"), reason))
    conn.commit()
    if cur.rowcount != 1:
        return False
    if audit is not None:
        audit.write("loka_capped", workspace=workspace, reason=reason)
    if notifier is None:
        return False
    try:
        notifier.send(cap_notice(workspace, reason), "Jarvis")
    except Exception:  # noqa: BLE001 - a failed notice must not stop the caller
        return False
    return True


def cap_notice(workspace: str, reason: str) -> str:
    return (f"Daily budget for office '{workspace}' reached ({reason}). Its unattended runs and tasks "
            "wait until tomorrow. Change the cap in that workspace's workspace.yaml (budget:).")


def tracker_hook(meter: LokaMeter) -> Callable[[int, float], str | None]:
    """The callable `BudgetTracker.extra` expects."""
    return meter.charge
