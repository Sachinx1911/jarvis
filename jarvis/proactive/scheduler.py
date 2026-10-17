"""Skill, agent and prompt schedules (PLAN.md 10.3).

- A schedule's truth is its file data/schedules/<id>.json (law 2, jarvis/core/truth.py); the
  sched_schedules row is the index, rewritten through to the file on every change and rebuilt
  from it by `jarvis rebuild`. Every run is recorded in sched_runs, which is the run's receipt
  (a measurement: SQLite only). APScheduler only fires the triggers; it keeps nothing of its
  own, so the database stays consistent across restarts.
- Unattended runs may do T0/T1 only. They get an approver that says no to everything,
  so a T2+ action never runs without Sachin. Each refused action is stored in
  sched_pending_approvals so Telegram can show it later.
- Missed runs (machine asleep or off): run once if within the grace window, else skip
  and record "missed". Several missed runs collapse into one (coalesce).
- Overlap: a run does not start while the previous one is still going. APScheduler's
  max_instances=1 covers the daemon; a lock row in the database also covers a
  `run-now` from the CLI while the daemon is running the same schedule.
- Every run opens its own database connection: SQLite connections must stay in the
  thread that made them, and APScheduler runs jobs in worker threads.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from jarvis.control.approvals import ApprovalRequest, Approver
from jarvis.control.audit import AuditLog
from jarvis.proactive.guard import CAPPED, UnattendedGuard, cap_notice, capped_today
from jarvis.control.stop import EmergencyStop, StopSwitch
from jarvis.core import truth
from jarvis.core.loop import BudgetExceeded
from jarvis.db import notional_usd
from jarvis.proactive.schedule_parse import KINDS, OUTPUTS, ScheduleDraft, trigger
from jarvis.providers.base import LLMResponse, ProviderError
from jarvis.routing.policy import RoutingError

log = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sched_schedules (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    target TEXT NOT NULL DEFAULT '',
    input TEXT NOT NULL DEFAULT '',
    cron TEXT NOT NULL,
    timezone TEXT NOT NULL,
    output TEXT NOT NULL,
    budget TEXT NOT NULL DEFAULT '{}',
    misfire_grace_s INTEGER NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    source TEXT NOT NULL DEFAULT 'cli',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    next_run_at TEXT,
    last_run_at TEXT,
    last_status TEXT,
    last_detail TEXT,
    last_output TEXT,
    running_since TEXT,
    workspace TEXT NOT NULL DEFAULT 'personal',
    archived_at TEXT
);
CREATE TABLE IF NOT EXISTS sched_runs (
    id INTEGER PRIMARY KEY,
    schedule_id TEXT NOT NULL,
    trigger TEXT NOT NULL,          -- cron | catch-up | run-now
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,           -- running | ok | quiet | failed | budget | stopped | missed | skipped_overlap | capped
    detail TEXT,
    output_path TEXT,
    model_calls INTEGER NOT NULL DEFAULT 0,
    notional_usd REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS sched_runs_schedule ON sched_runs(schedule_id);
CREATE TABLE IF NOT EXISTS sched_pending_approvals (
    id INTEGER PRIMARY KEY,
    schedule_id TEXT,
    run_id INTEGER,
    created_at TEXT NOT NULL,
    tool TEXT NOT NULL,
    tier TEXT NOT NULL,
    arguments TEXT NOT NULL,
    reason TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',  -- see PendingApprovals
    decided_at TEXT,
    result TEXT,
    ok INTEGER,
    verified INTEGER
);
"""

_COLS = truth.SPECS["schedules"].cols


@dataclass
class Schedule:
    id: str
    name: str
    kind: str
    target: str
    input: str
    cron: str
    timezone: str
    output: str
    budget: dict[str, Any]
    misfire_grace_s: int
    enabled: bool
    source: str
    created_at: str
    updated_at: str
    next_run_at: str | None = None
    last_run_at: str | None = None
    last_status: str | None = None
    last_detail: str | None = None
    last_output: str | None = None
    workspace: str = "personal"
    running_since: str | None = None
    archived_at: str | None = None   # law 2: ended, never deleted; hidden from lists, cannot run

    @property
    def archived(self) -> bool:
        return bool(self.archived_at)

    def next_after(self, now: datetime) -> datetime | None:
        return trigger(self.cron, self.timezone).get_next_fire_time(None, now)

    def line(self) -> str:
        state = "enabled" if self.enabled else "PAUSED"
        last = f", last {self.last_status} {self.last_run_at[:16]}" if self.last_run_at else ""
        nxt = f", next {self.next_run_at[:16]}" if self.enabled and self.next_run_at else ""
        what = self.target or self.input
        return f"{self.id} [{state}] {self.name} | {self.kind}{': ' + what[:40] if what else ''} | {self.cron}{nxt}{last}"


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


class ScheduleStore:
    def __init__(self, conn: sqlite3.Connection, home: Path | None = None):
        self.db = conn
        self.home = home or truth.home_of(conn)   # None (in-memory database): no file truth to write
        self.db.executescript(_SCHEMA)
        have = {r[1] for r in self.db.execute("PRAGMA table_info(sched_schedules)")}
        for column, decl in (("workspace", "TEXT NOT NULL DEFAULT 'personal'"), ("archived_at", "TEXT")):
            if column not in have:  # databases from before workspaces / archive existed
                try:
                    self.db.execute(f"ALTER TABLE sched_schedules ADD COLUMN {column} {decl}")
                except sqlite3.OperationalError as e:  # another connection added it in between
                    if "duplicate column" not in str(e).lower():
                        raise
        self.db.commit()

    def _next_id(self) -> str:
        nums = [int(r[0][2:]) for r in self.db.execute("SELECT id FROM sched_schedules") if r[0][2:].isdigit()]
        return f"s-{(max(nums) + 1) if nums else 1:03d}"

    def _sync(self, sid: str) -> None:
        """Write-through (law 2): the row's truth goes to data/schedules/<id>.json after every change."""
        if self.home is None:
            return
        row = self.db.execute(f"SELECT {', '.join(_COLS)} FROM sched_schedules WHERE id=?", (sid,)).fetchone()
        if row:
            truth.write_truth(self.home, "schedules", sid, truth.SPECS["schedules"].record_of_row(dict(zip(_COLS, row))))

    def add(self, draft: ScheduleDraft, now: datetime, misfire_grace_s: int, source: str = "cli") -> Schedule:
        if draft.kind not in KINDS:
            raise ValueError(f"kind must be one of {', '.join(KINDS)}")
        if draft.output not in OUTPUTS:
            raise ValueError(f"output must be one of {', '.join(OUTPUTS)}")
        if draft.kind in ("skill", "agent") and not draft.target:
            raise ValueError(f"a {draft.kind} schedule needs a {draft.kind} name")
        nxt = trigger(draft.cron, draft.timezone).get_next_fire_time(None, now)  # validates cron + tz
        sid = self._next_id()
        self.db.execute(
            f"INSERT INTO sched_schedules ({', '.join(_COLS[:15])}, workspace) VALUES ({', '.join('?' * 16)})",
            (sid, draft.name, draft.kind, draft.target, draft.input, draft.cron, draft.timezone, draft.output,
             json.dumps(draft.budget), int(misfire_grace_s), 1, source, _iso(now), _iso(now),
             _iso(nxt) if nxt else None, getattr(draft, "workspace", "personal") or "personal"))
        self.db.commit()
        self._sync(sid)
        return self.get(sid)  # type: ignore[return-value]

    def get(self, sid: str) -> Schedule | None:
        row = self.db.execute(f"SELECT {', '.join(_COLS)} FROM sched_schedules WHERE id=?", (sid,)).fetchone()
        if not row:
            return None
        data = dict(zip(_COLS, row))
        data["budget"] = json.loads(data["budget"] or "{}")
        data["enabled"] = bool(data["enabled"])
        return Schedule(**data)

    def find(self, name: str) -> Schedule | None:
        row = self.db.execute("SELECT id FROM sched_schedules WHERE name=? ORDER BY id LIMIT 1", (name,)).fetchone()
        return self.get(row[0]) if row else None

    def list(self, include_archived: bool = False) -> list[Schedule]:
        where = "" if include_archived else " WHERE archived_at IS NULL"
        return [self.get(r[0]) for r in self.db.execute(f"SELECT id FROM sched_schedules{where} ORDER BY id")]  # type: ignore[misc]

    def set_enabled(self, sid: str, enabled: bool, now: datetime) -> Schedule:
        s = self.get(sid)
        if not s:
            raise KeyError(sid)
        nxt = s.next_after(now) if enabled else None
        self.db.execute("UPDATE sched_schedules SET enabled=?, next_run_at=?, updated_at=? WHERE id=?",
                        (int(enabled), _iso(nxt) if nxt else None, _iso(now), sid))
        self.db.commit()
        self._sync(sid)
        return self.get(sid)  # type: ignore[return-value]

    def archive(self, sid: str, now: datetime) -> bool:
        """End (law 2, Mahesh): the schedule stops, leaves every list, keeps its id and history."""
        cur = self.db.execute("UPDATE sched_schedules SET archived_at=?, enabled=0, next_run_at=NULL, updated_at=? "
                              "WHERE id=? AND archived_at IS NULL", (_iso(now), _iso(now), sid))
        self.db.commit()
        if cur.rowcount:
            self._sync(sid)
        return cur.rowcount == 1

    def unarchive(self, sid: str, now: datetime) -> bool:
        cur = self.db.execute("UPDATE sched_schedules SET archived_at=NULL, updated_at=? "
                              "WHERE id=? AND archived_at IS NOT NULL", (_iso(now), sid))
        self.db.commit()
        if cur.rowcount:
            self._sync(sid)
        return cur.rowcount == 1

    def delete_forever(self, sid: str) -> bool:
        """Sachin's explicit, logged act only (law 2): callers must have asked him and must audit it.
        Works on an archived schedule only, so a live one is always archived first. The truth file
        goes with the row: this is the one place a schedule file is removed."""
        cur = self.db.execute("DELETE FROM sched_schedules WHERE id=? AND archived_at IS NOT NULL", (sid,))
        self.db.commit()
        if cur.rowcount and self.home is not None:
            truth.remove_truth(self.home, "schedules", sid)
        return cur.rowcount == 1

    def set_next(self, sid: str, nxt: datetime | None) -> None:
        self.db.execute("UPDATE sched_schedules SET next_run_at=? WHERE id=?", (_iso(nxt) if nxt else None, sid))
        self.db.commit()
        self._sync(sid)

    # ---- overlap lock (works across threads and processes) ----

    def acquire(self, sid: str, now: datetime, stale_after: timedelta) -> bool:
        cutoff = _iso(now - stale_after)
        cur = self.db.execute(
            "UPDATE sched_schedules SET running_since=? WHERE id=? AND (running_since IS NULL OR running_since < ?)",
            (_iso(now), sid, cutoff))
        self.db.commit()
        return cur.rowcount == 1

    def release(self, sid: str) -> None:
        self.db.execute("UPDATE sched_schedules SET running_since=NULL WHERE id=?", (sid,))
        self.db.commit()

    # ---- runs ----

    def start_run(self, sid: str, trigger_kind: str, now: datetime) -> int:
        cur = self.db.execute("INSERT INTO sched_runs (schedule_id, trigger, started_at, status) VALUES (?, ?, ?, ?)",
                              (sid, trigger_kind, _iso(now), "running"))
        self.db.commit()
        return int(cur.lastrowid)  # type: ignore[arg-type]

    def finish_run(self, run_id: int, sid: str, status: str, detail: str, now: datetime,
                   output_path: str | None = None, calls: int = 0, usd: float = 0.0) -> None:
        self.db.execute(
            """UPDATE sched_runs SET finished_at=?, status=?, detail=?, output_path=?, model_calls=?, notional_usd=?
               WHERE id=?""", (_iso(now), status, detail[:2000], output_path, calls, round(usd, 6), run_id))
        self.db.execute(
            """UPDATE sched_schedules SET last_run_at=?, last_status=?, last_detail=?, last_output=? WHERE id=?""",
            (_iso(now), status, detail[:500], output_path, sid))
        self.db.commit()
        self._sync(sid)

    def record(self, sid: str, trigger_kind: str, status: str, detail: str, now: datetime) -> int:
        """A run that did not start (missed, overlap, stopped)."""
        run_id = self.start_run(sid, trigger_kind, now)
        self.finish_run(run_id, sid, status, detail, now)
        return run_id

    def runs(self, sid: str, limit: int = 10) -> list[dict[str, Any]]:
        rows = self.db.execute(
            """SELECT id, trigger, started_at, finished_at, status, detail, output_path, model_calls, notional_usd
               FROM sched_runs WHERE schedule_id=? ORDER BY id DESC LIMIT ?""", (sid, limit)).fetchall()
        keys = ("id", "trigger", "started_at", "finished_at", "status", "detail", "output_path", "model_calls",
                "notional_usd")
        return [dict(zip(keys, r)) for r in rows]


_PENDING_EXTRA_COLS = {"decided_at": "TEXT", "result": "TEXT", "ok": "INTEGER", "verified": "INTEGER"}
_PENDING_KEYS = ("id", "schedule_id", "run_id", "created_at", "tool", "tier", "arguments", "reason", "status",
                 "decided_at", "result", "ok", "verified")


class PendingApprovals:
    """Actions an unattended run wanted but was not allowed to do.

    status: pending -> dismissed | denied | stale | refused | running -> executed | failed.
    Approving replays the exact stored call once (jarvis/proactive/replay.py).
    """

    def __init__(self, conn: sqlite3.Connection):
        self.db = conn
        self.db.executescript(_SCHEMA)
        have = {r[1] for r in self.db.execute("PRAGMA table_info(sched_pending_approvals)")}
        for col, kind in _PENDING_EXTRA_COLS.items():  # databases made before these columns existed
            if col not in have:
                try:
                    self.db.execute(f"ALTER TABLE sched_pending_approvals ADD COLUMN {col} {kind}")
                except sqlite3.OperationalError as e:  # another connection added it in between
                    if "duplicate column" not in str(e).lower():
                        raise
        self.db.commit()

    def get(self, pid: int) -> dict[str, Any] | None:
        row = self.db.execute(f"SELECT {', '.join(_PENDING_KEYS)} FROM sched_pending_approvals WHERE id=?",
                              (pid,)).fetchone()
        if not row:
            return None
        data = dict(zip(_PENDING_KEYS, row))
        data["arguments"] = json.loads(data["arguments"])
        return data

    def set_status(self, pid: int, status: str, now: datetime, from_status: str = "pending") -> bool:
        """Atomic: only moves an item that is still in `from_status` (a second click does nothing)."""
        cur = self.db.execute("UPDATE sched_pending_approvals SET status=?, decided_at=? WHERE id=? AND status=?",
                              (status, _iso(now), pid, from_status))
        self.db.commit()
        return cur.rowcount == 1

    def finish(self, pid: int, status: str, result: str, ok: bool, verified: bool | None, now: datetime) -> None:
        self.db.execute(
            "UPDATE sched_pending_approvals SET status=?, decided_at=?, result=?, ok=?, verified=? WHERE id=?",
            (status, _iso(now), result[:4000], int(ok), None if verified is None else int(verified), pid))
        self.db.commit()

    def add(self, schedule_id: str | None, run_id: int | None, req: ApprovalRequest, now: datetime) -> int:
        cur = self.db.execute(
            """INSERT INTO sched_pending_approvals (schedule_id, run_id, created_at, tool, tier, arguments, reason)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (schedule_id, run_id, _iso(now), req.tool, req.tier, json.dumps(req.arguments, ensure_ascii=False),
             req.reason))
        self.db.commit()
        return int(cur.lastrowid)  # type: ignore[arg-type]

    def list(self, status: str = "pending") -> list[dict[str, Any]]:
        rows = self.db.execute(
            """SELECT id, schedule_id, run_id, created_at, tool, tier, arguments, reason FROM sched_pending_approvals
               WHERE status=? ORDER BY id""", (status,)).fetchall()
        keys = ("id", "schedule_id", "run_id", "created_at", "tool", "tier", "arguments", "reason")
        return [dict(zip(keys, r)) | {"arguments": json.loads(r[6])} for r in rows]

    def count_for_run(self, run_id: int) -> int:
        return self.db.execute("SELECT COUNT(*) FROM sched_pending_approvals WHERE run_id=?", (run_id,)).fetchone()[0]

    def for_run(self, run_id: int) -> list[dict[str, Any]]:
        """Id, tool and tier of each action a run wanted but was refused (no arguments: this goes
        into the run receipt and over Telegram)."""
        rows = self.db.execute("SELECT id, tool, tier FROM sched_pending_approvals WHERE run_id=? ORDER BY id",
                               (run_id,)).fetchall()
        return [{"id": r[0], "tool": r[1], "tier": r[2]} for r in rows]

    def dismiss(self, pid: int) -> bool:
        cur = self.db.execute("UPDATE sched_pending_approvals SET status='dismissed' WHERE id=? AND status='pending'",
                              (pid,))
        self.db.commit()
        return cur.rowcount == 1


def unattended_approver(pending: PendingApprovals, schedule_id: str | None, run_id: int | None,
                        clock: Callable[[], datetime], audit: AuditLog | None = None) -> Approver:
    """Says no to every approval request (so only T0/T1 runs), and queues it for Sachin."""
    def approve(req: ApprovalRequest) -> bool:
        pid = pending.add(schedule_id, run_id, req, clock())
        if audit:
            audit.write("unattended_denied", schedule_id=schedule_id, run_id=run_id, tool=req.tool, tier=req.tier,
                        pending_id=pid)
        return False
    return approve


class RunBudget:
    """Per-run limit, enforced after every model call through the agent loop's usage hook."""

    def __init__(self, max_model_calls: int | None = None, max_notional_usd: float | None = None):
        self.max_calls = max_model_calls
        self.max_usd = max_notional_usd
        self.calls = 0
        self.usd = 0.0

    def __call__(self, resp: LLMResponse) -> None:
        self.calls += 1
        self.usd += notional_usd(resp) or 0.0
        if self.max_calls is not None and self.calls >= self.max_calls + 1:
            raise BudgetExceeded(f"more than {self.max_calls} model calls")
        if self.max_usd is not None and self.usd > self.max_usd:
            raise BudgetExceeded(f"over ${self.max_usd:.2f} (notional)")


@dataclass
class RunContext:
    """What a kind executor gets for one run."""
    schedule: Schedule
    rt: Any                     # jarvis.core.runtime.Runtime (or a test double with the same fields)
    approver: Approver
    budget: RunBudget
    run_id: int
    now: datetime


# kind executor: returns the text to deliver, or None when there is nothing to say.
Executor = Callable[[RunContext], "str | None"]


@dataclass
class RunResult:
    schedule_id: str
    run_id: int | None
    status: str
    text: str = ""
    output_path: str | None = None
    pending: int = 0


def unattended_header(s: Schedule) -> str:
    return (f"[Scheduled run of {s.id} '{s.name}'. Sachin is not watching: any action that needs approval "
            f"will be refused and queued for him. Do only read-only work and new files.]\n")


def chat_executor(chat_factory: Callable[[Any, Approver], Any]) -> Executor:
    """prompt and skill schedules: one ChatSession turn with the unattended approver."""
    def run(ctx: RunContext) -> str | None:
        s = ctx.schedule
        session = chat_factory(ctx.rt, ctx.approver)
        session.loop.on_usage = ctx.budget
        if s.kind == "skill":
            text = f"Run the skill '{s.target}' now (load it with load_skill first). Input: {s.input or '(none)'}"
        else:
            text = s.input
        return session.send(unattended_header(s) + text)
    return run


def queue_agent_task(ctx: RunContext) -> str:
    """Default for agent schedules: put a task in the queue for that agent. The agent team
    (Phase 3) picks it up; replace this executor once the team runner exists."""
    from jarvis.tasks.store import TaskStore

    s = ctx.schedule
    tasks = TaskStore(ctx.rt.store, ctx.rt.paths.data / "tasks")
    task = tasks.create(goal=s.input or s.name, title=s.name, budget=s.budget or None,
                        workspace=getattr(s, "workspace", "personal") or "personal")
    tasks.update(task.id, owner=s.target)
    tasks.event(task.id, "scheduled", {"schedule_id": s.id, "run_id": ctx.run_id})
    return f"Queued task {task.id} for agent {s.target}: {task.title}"


class ScheduleRunner:
    """Runs one schedule once: lock, execute, write output, notify, record the receipt."""

    def __init__(self, open_rt: Callable[[], Any], executors: dict[str, Executor], notifier=None,
                 clock: Callable[[], datetime] | None = None, stale_lock: timedelta = timedelta(hours=6),
                 default_budget: dict[str, Any] | None = None, guard: UnattendedGuard | None = None):
        self.open_rt = open_rt
        self.executors = executors
        self.notifier = notifier
        self.clock = clock or (lambda: datetime.now().astimezone())
        self.stale_lock = stale_lock
        self.default_budget = default_budget or {}
        self.guard = guard  # global daily cap + pause after repeated failures (jarvis/proactive/guard.py)

    def run(self, sid: str, trigger_kind: str = "run-now") -> RunResult:
        rt = self.open_rt()
        try:
            return self._run(rt, sid, trigger_kind)
        finally:
            rt.close()

    def record(self, sid: str, trigger_kind: str, status: str, detail: str) -> None:
        rt = self.open_rt()
        try:
            store = ScheduleStore(rt.store.conn)
            if store.get(sid):
                store.record(sid, trigger_kind, status, detail, self.clock())
                rt.audit.write("schedule_run", schedule_id=sid, trigger=trigger_kind, status=status, detail=detail)
        finally:
            rt.close()

    def _run(self, rt: Any, sid: str, trigger_kind: str) -> RunResult:
        store = ScheduleStore(rt.store.conn)
        s = store.get(sid)
        now = self.clock()
        if s is None:
            return RunResult(sid, None, "unknown")
        if not s.enabled and trigger_kind != "run-now":
            return RunResult(sid, None, "paused")
        if s.kind not in self.executors:
            run_id = store.record(sid, trigger_kind, "failed", f"no executor for kind {s.kind}", now)
            return RunResult(sid, run_id, "failed", f"no executor for kind {s.kind}")
        if StopSwitch(rt.paths.data).engaged():
            run_id = store.record(sid, trigger_kind, "stopped", "emergency stop is on", now)
            rt.audit.write("schedule_run", schedule_id=sid, trigger=trigger_kind, status="stopped")
            if trigger_kind != "run-now":
                store.set_next(sid, s.next_after(now))
            return RunResult(sid, run_id, "stopped")
        attended = trigger_kind == "run-now"   # Sachin started it himself: counted, never capped
        if self.guard is not None and not attended:
            reason = self.guard.over_cap(rt.store.conn, now)
            if reason:
                first = not capped_today(rt.store.conn, now)
                run_id = store.record(sid, trigger_kind, CAPPED, f"daily cap reached: {reason}", now)
                rt.audit.write("schedule_run", schedule_id=sid, trigger=trigger_kind, status=CAPPED, detail=reason)
                store.set_next(sid, s.next_after(now))
                if first and self.notifier is not None:
                    try:
                        self.notifier.send(cap_notice(reason), "Jarvis")
                    except Exception:  # noqa: BLE001 - a failed notice must not stop the scheduler
                        log.exception("cap notice failed")
                return RunResult(sid, run_id, CAPPED, f"Not run: daily cap reached ({reason}).")
        if not attended:   # Kubera (27.4): the office's own daily budget
            from jarvis.control import loka_budget
            from jarvis.workspaces.store import WorkspaceStore

            try:
                cfg = WorkspaceStore(rt.paths.home).get(s.workspace)
            except Exception:  # noqa: BLE001 - no workspace file: no office cap
                cfg = None
            reason = loka_budget.allow_unattended(rt.store.conn, s.workspace, cfg, now)
            if reason:
                run_id = store.record(sid, trigger_kind, CAPPED, reason, now)
                rt.audit.write("schedule_run", schedule_id=sid, trigger=trigger_kind, status=CAPPED, detail=reason)
                store.set_next(sid, s.next_after(now))
                loka_budget.notify_capped(rt.store.conn, s.workspace, reason, self.notifier, now, rt.audit)
                return RunResult(sid, run_id, CAPPED, f"Not run: {reason}.")
        if not store.acquire(sid, now, self.stale_lock):
            run_id = store.record(sid, trigger_kind, "skipped_overlap", "previous run still going", now)
            rt.audit.write("schedule_run", schedule_id=sid, trigger=trigger_kind, status="skipped_overlap")
            return RunResult(sid, run_id, "skipped_overlap")

        run_id = store.start_run(sid, trigger_kind, now)
        limits = {**self.default_budget, **(s.budget or {})}
        if self.guard is not None and not attended:
            budget = RunBudget(*self.guard.clip(limits, rt.store.conn, now))
        else:
            budget = RunBudget(limits.get("max_model_calls"), limits.get("max_notional_usd"))
        pending = PendingApprovals(rt.store.conn)
        approver = unattended_approver(pending, sid, run_id, self.clock, rt.audit)
        status, text = "ok", ""
        try:
            out = self.executors[s.kind](RunContext(s, rt, approver, budget, run_id, now))
            if out is None:
                status = "quiet"  # e.g. heartbeat: nothing worth saying
            else:
                text = out
        except BudgetExceeded as e:
            status, text = "budget", f"Stopped: budget reached ({e})."
        except EmergencyStop as e:
            status, text = "stopped", f"Stopped: {e}"
        except (ProviderError, RoutingError) as e:
            status, text = "failed", f"Failed: {type(e).__name__}: {e}"
        except Exception as e:  # noqa: BLE001 - one bad run must not kill the scheduler
            log.exception("schedule %s failed", sid)
            status, text = "failed", f"Failed: {type(e).__name__}: {e}"
        finally:
            store.release(sid)

        waiting = pending.count_for_run(run_id)
        if waiting:
            # The run receipt (sched_runs.detail, the output file, Telegram) lists every refused action.
            held = pending.for_run(run_id)
            text += (f"\n\n{waiting} action(s) need your approval and did not run. "
                     f"See /approvals on Telegram or `jarvis schedule approvals`.\n"
                     + "\n".join(f"- #{a['id']} {a['tool']} ({a['tier']}): refused unattended, waiting for approval"
                                 for a in held[:10])
                     + (f"\n- ... and {waiting - 10} more" if waiting > 10 else ""))
        done = self.clock()
        output_path = None
        if status != "quiet" and s.output in ("file", "both"):
            output_path = str(self._write_output(rt, s, run_id, status, text, done))
        delivered = ""
        if status != "quiet" and s.output in ("telegram", "both") and self.notifier is not None:
            # The brief and heartbeat speak for themselves; other runs say which schedule they came from.
            if s.kind in ("brief", "heartbeat") and status == "ok":
                message, title = text, ("Daily brief" if s.kind == "brief" else "Jarvis")
            else:
                message, title = f"{s.name} ({s.id}, {status})\n{text}".strip(), "Schedule"
            try:
                delivered = self.notifier.send(message, title) or ""
            except Exception as e:  # noqa: BLE001
                delivered = f"notify failed: {e}"
        store.finish_run(run_id, sid, status, text or status, done, output_path, budget.calls, budget.usd)
        if trigger_kind != "run-now":
            store.set_next(sid, s.next_after(done))
        rt.audit.write("schedule_run", schedule_id=sid, run_id=run_id, trigger=trigger_kind, status=status,
                       model_calls=budget.calls, pending_approvals=waiting, output=output_path, delivered=delivered)
        if self.guard is not None and status in ("failed", "budget"):
            self._maybe_pause(rt, store, s, done)
        return RunResult(sid, run_id, status, text, output_path, waiting)

    def _maybe_pause(self, rt: Any, store: "ScheduleStore", s: Schedule, now: datetime) -> None:
        """Runaway guard: pause a schedule that failed several times in a row, and say so."""
        assert self.guard is not None
        n = self.guard.pause_after_failures
        statuses = [r["status"] for r in store.runs(s.id, limit=max(n * 4, 10))]
        current = store.get(s.id)
        if current is None or not current.enabled or not self.guard.should_pause(statuses):
            return
        store.set_enabled(s.id, False, now)
        rt.audit.write("schedule_auto_paused", schedule_id=s.id, failures_in_a_row=n)
        if self.notifier is not None:
            try:
                self.notifier.send(f"Paused schedule {s.name} ({s.id}) after {n} failed runs in a row. "
                                   f"Last result: {current.last_detail or '-'}. Resume: jarvis schedule resume {s.id}",
                                   "Jarvis")
            except Exception:  # noqa: BLE001
                log.exception("pause notice failed")

    @staticmethod
    def _write_output(rt: Any, s: Schedule, run_id: int, status: str, text: str, now: datetime) -> Path:
        folder = Path(rt.paths.data) / "schedules" / s.id
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{now:%Y%m%d-%H%M%S}-run{run_id}.md"
        path.write_text(f"# {s.name} ({s.id})\n\n- When: {_iso(now)}\n- Status: {status}\n- Schedule: {s.cron} "
                        f"({s.timezone})\n\n{text}\n", encoding="utf-8")
        return path


# ---------------------------------------------------------------- missed runs


def _short_time(value: str | None) -> str:
    try:
        return datetime.fromisoformat(str(value)).strftime("%a %d %b %H:%M")
    except (TypeError, ValueError):
        return str(value)


def missed_run_action(next_run_at: datetime, now: datetime, grace: timedelta) -> str | None:
    """'run' (late but within grace), 'skip' (too late), or None (not due yet)."""
    if next_run_at > now:
        return None
    return "run" if now - next_run_at <= grace else "skip"


class ScheduleService:
    """APScheduler-driven daemon side. The database is the source of truth; `sync` brings
    APScheduler's jobs in line with it (new, paused, deleted or changed schedules)."""

    def __init__(self, runner: ScheduleRunner, tz: str, sync_seconds: int = 60,
                 extra_jobs: list[tuple[Callable[[], None], int, str]] | None = None,
                 alert_missed: bool = True, quiet_kinds: tuple[str, ...] = ("heartbeat", "memory_extract")):
        self.runner = runner
        self.tz = tz
        # Tell Sachin when a run was missed (machine asleep or off past the grace window). Frequent
        # checks (heartbeat, memory extraction) miss whenever the laptop sleeps, so they stay quiet.
        self.alert_missed = alert_missed
        self.quiet_kinds = tuple(quiet_kinds)
        self.sync_seconds = sync_seconds
        self.extra_jobs = extra_jobs or []   # (function, every_seconds, job id): e.g. the reminder check
        self.scheduler = None
        self._sigs: dict[str, tuple] = {}
        self._lock = threading.Lock()

    def _store(self) -> tuple[Any, ScheduleStore]:
        rt = self.runner.open_rt()
        return rt, ScheduleStore(rt.store.conn)

    def catch_up(self, now: datetime | None = None) -> list[RunResult]:
        """At start: handle runs that came due while Jarvis was not running."""
        now = now or self.runner.clock()
        rt, store = self._store()
        try:
            due: list[str] = []
            missed: list[str] = []
            for s in store.list():
                if not s.enabled:
                    continue
                if not s.next_run_at:
                    store.set_next(s.id, s.next_after(now))
                    continue
                action = missed_run_action(datetime.fromisoformat(s.next_run_at), now,
                                           timedelta(seconds=s.misfire_grace_s))
                if action == "run":
                    due.append(s.id)
                elif action == "skip":
                    store.record(s.id, "catch-up", "missed", f"was due {s.next_run_at}; past the grace window", now)
                    rt.audit.write("schedule_run", schedule_id=s.id, trigger="catch-up", status="missed")
                    store.set_next(s.id, s.next_after(now))
                    if s.kind not in self.quiet_kinds:
                        missed.append(f"{s.name} ({s.id}, was due {_short_time(s.next_run_at)})")
        finally:
            rt.close()
        self._alert_missed(missed)
        return [self.runner.run(sid, "catch-up") for sid in due]  # one run each, however many were missed

    def _alert_missed(self, lines: list[str]) -> None:
        if not lines or not self.alert_missed or self.runner.notifier is None:
            return
        text = ("Missed while Jarvis was off or the computer was asleep (past the grace window):\n"
                + "\n".join(f"- {line}" for line in lines) + "\nThey run again at their next time; "
                "use Run now in the Schedules tab (or `jarvis schedule run-now <id>`) if needed.")
        try:
            self.runner.notifier.send(text, "Jarvis")
        except Exception:  # noqa: BLE001 - a failed notice must not stop the scheduler
            log.exception("missed-run notice failed")

    # ---- APScheduler ----

    def _fire(self, sid: str) -> None:
        self.runner.run(sid, "cron")

    def _on_event(self, event) -> None:
        from apscheduler.events import EVENT_JOB_MAX_INSTANCES, EVENT_JOB_MISSED

        sid = event.job_id
        if not sid.startswith("s-"):
            return
        if event.code == EVENT_JOB_MISSED:
            self.runner.record(sid, "cron", "missed", f"was due {event.scheduled_run_time}; past the grace window")
            rt, store = self._store()
            try:
                s = store.get(sid)
            finally:
                rt.close()
            if s is not None and s.kind not in self.quiet_kinds:
                self._alert_missed([f"{s.name} ({s.id}, was due {_short_time(str(event.scheduled_run_time))})"])
        elif event.code == EVENT_JOB_MAX_INSTANCES:
            self.runner.record(sid, "cron", "skipped_overlap", "previous run still going")

    def start(self) -> None:
        from apscheduler.events import EVENT_JOB_MAX_INSTANCES, EVENT_JOB_MISSED
        from apscheduler.schedulers.background import BackgroundScheduler

        self.scheduler = BackgroundScheduler(timezone=self.tz)
        self.scheduler.add_listener(self._on_event, EVENT_JOB_MISSED | EVENT_JOB_MAX_INSTANCES)
        self.sync()
        self.scheduler.add_job(self.sync, "interval", seconds=self.sync_seconds, id="_sync",
                               coalesce=True, max_instances=1, misfire_grace_time=self.sync_seconds)
        for fn, every, job_id in self.extra_jobs:
            self.scheduler.add_job(fn, "interval", seconds=every, id=job_id, coalesce=True, max_instances=1,
                                   misfire_grace_time=max(every, 30))
        self.scheduler.start()

    def shutdown(self) -> None:
        if self.scheduler is not None:
            self.scheduler.shutdown(wait=False)
            self.scheduler = None

    def sync(self) -> None:
        if self.scheduler is None:
            return
        with self._lock:
            rt, store = self._store()
            try:
                wanted = {s.id: s for s in store.list() if s.enabled}
            finally:
                rt.close()
            for sid in list(self._sigs):
                if sid not in wanted:
                    if self.scheduler.get_job(sid):
                        self.scheduler.remove_job(sid)
                    del self._sigs[sid]
            for sid, s in wanted.items():
                sig = (s.cron, s.timezone, s.misfire_grace_s)
                if self._sigs.get(sid) == sig and self.scheduler.get_job(sid):
                    continue
                self.scheduler.add_job(
                    self._fire, trigger(s.cron, s.timezone), args=[sid], id=sid, name=s.name,
                    replace_existing=True, misfire_grace_time=s.misfire_grace_s, coalesce=True, max_instances=1)
                self._sigs[sid] = sig
