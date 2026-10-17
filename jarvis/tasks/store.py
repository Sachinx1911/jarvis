"""Task queue and states (PLAN.md 10.1). No task becomes COMPLETED without VERIFYING.

File truth (law 2, jarvis/core/truth.py): every change to a task row rewrites data/tasks/<id>/task.json
and every event is appended to data/tasks/<id>/events.jsonl; the SQLite rows are the index that
`jarvis rebuild` recreates from those files. A finished task ends by archive (Mahesh), never by delete.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jarvis.core import truth
from jarvis.db import Store

STATES = ("BACKLOG", "SCHEDULED", "PLANNED", "RUNNING", "WAITING_APPROVAL", "VERIFYING",
          "PAUSED", "COMPLETED", "FAILED", "CANCELLED")
FINAL = {"COMPLETED", "FAILED", "CANCELLED"}
TRANSITIONS: dict[str, set[str]] = {
    "BACKLOG": {"PLANNED", "SCHEDULED", "CANCELLED", "FAILED"},
    "SCHEDULED": {"PLANNED", "CANCELLED", "PAUSED"},
    "PLANNED": {"RUNNING", "CANCELLED", "PAUSED", "FAILED"},
    "RUNNING": {"WAITING_APPROVAL", "VERIFYING", "PAUSED", "FAILED", "CANCELLED"},
    "WAITING_APPROVAL": {"RUNNING", "CANCELLED", "FAILED"},
    "VERIFYING": {"COMPLETED", "FAILED", "RUNNING"},
    "PAUSED": {"PLANNED", "RUNNING", "CANCELLED"},
    "COMPLETED": set(),
    "FAILED": {"PLANNED"},      # a failed task may be retried
    "CANCELLED": set(),
}
PRIORITIES = {"high": 1, "normal": 2, "low": 3}


class TransitionError(ValueError):
    pass


@dataclass
class Task:
    id: str
    title: str
    goal: str
    state: str
    project: str | None = None
    priority: int = 2
    deadline: str | None = None
    owner: str = "jarvis"
    budget: dict[str, Any] = field(default_factory=dict)
    plan: dict[str, Any] = field(default_factory=dict)
    checkpoint: dict[str, Any] = field(default_factory=dict)
    last_error: str | None = None
    retries: int = 0
    current_step: str | None = None
    created_at: str = ""
    updated_at: str = ""
    workspace: str = "personal"  # the office the task belongs to
    archived_at: str | None = None   # law 2: a finished task is put away, never deleted

    @property
    def archived(self) -> bool:
        return bool(self.archived_at)


_COLS = truth.SPECS["tasks"].cols
_JSON = {"budget", "plan", "checkpoint"}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")   # the same form as SQLite's datetime('now')


class TaskStore:
    def __init__(self, store: Store, tasks_dir: Path):
        self.store = store
        self.db = store.conn
        self.tasks_dir = tasks_dir
        have = {r[1] for r in self.db.execute("PRAGMA table_info(tasks)")}
        if "archived_at" not in have:  # databases from before task archive existed
            try:
                self.db.execute("ALTER TABLE tasks ADD COLUMN archived_at TEXT")
            except sqlite3.OperationalError as e:  # another connection added it in between
                if "duplicate column" not in str(e).lower():
                    raise
            self.db.commit()

    def folder(self, task_id: str) -> Path:
        path = self.tasks_dir / task_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    # ---- file truth (law 2): the folder's task.json is the truth, the row is its index ----

    def _sync(self, task_id: str) -> None:
        row = self.db.execute(f"SELECT {', '.join(_COLS)} FROM tasks WHERE id=?", (task_id,)).fetchone()
        if row:
            record = truth.SPECS["tasks"].record_of_row(dict(zip(_COLS, row)))
            truth.write_json(self.folder(task_id) / "task.json", {**record, "truth_version": truth.TRUTH_VERSION})

    def _next_id(self) -> str:
        nums = [int(r[0][2:]) for r in self.db.execute("SELECT id FROM tasks") if r[0][2:].isdigit()]
        return f"t-{(max(nums) + 1) if nums else 1:03d}"

    def create(self, goal: str, title: str | None = None, project: str | None = None, priority: int = 2,
               deadline: str | None = None, budget: dict | None = None, state: str = "BACKLOG",
               workspace: str = "personal") -> Task:
        task_id = self._next_id()
        self.db.execute(
            """INSERT INTO tasks (id, title, goal, state, project, priority, deadline, budget, workspace)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (task_id, (title or goal)[:80], goal, state, project, priority, deadline, json.dumps(budget or {}),
             workspace or "personal"),
        )
        self.db.commit()
        self._sync(task_id)
        self.event(task_id, "created", {"goal": goal, "project": project, "workspace": workspace or "personal"})
        return self.get(task_id)  # type: ignore[return-value]

    def get(self, task_id: str) -> Task | None:
        row = self.db.execute(f"SELECT {', '.join(_COLS)} FROM tasks WHERE id=?", (task_id,)).fetchone()
        if not row:
            return None
        data = dict(zip(_COLS, row))
        for k in _JSON:
            data[k] = json.loads(data[k]) if data[k] else {}
        return Task(**data)

    def list(self, include_final: bool = False, include_archived: bool = False) -> list[Task]:
        rows = self.db.execute("SELECT id FROM tasks ORDER BY priority, COALESCE(deadline, '9999'), id").fetchall()
        tasks = [self.get(r[0]) for r in rows]
        return [t for t in tasks if t and (include_final or t.state not in FINAL)
                and (include_archived or not t.archived_at)]

    def set_state(self, task_id: str, state: str, note: str = "") -> Task:
        task = self.get(task_id)
        if not task:
            raise KeyError(task_id)
        if state not in TRANSITIONS[task.state]:
            raise TransitionError(f"{task_id}: {task.state} -> {state} is not allowed")
        self.db.execute("UPDATE tasks SET state=?, updated_at=datetime('now') WHERE id=?", (state, task_id))
        self.db.commit()
        self._sync(task_id)
        if state == "CANCELLED":  # a running task (any thread) sees this file and stops
            (self.folder(task_id) / "CANCEL").write_text(note or "cancelled", encoding="utf-8")
        self.event(task_id, "state", {"from": task.state, "to": state, "note": note})
        return self.get(task_id)  # type: ignore[return-value]

    def archive(self, task_id: str, now: datetime | None = None) -> Task:
        """End (law 2, Mahesh): a finished task (COMPLETED, FAILED or CANCELLED) leaves the lists and keeps
        its folder, its events and its id. A task still in flight cannot be archived: cancel it first."""
        task = self.get(task_id)
        if not task:
            raise KeyError(task_id)
        if task.state not in FINAL:
            raise TransitionError(f"{task_id}: only a finished task can be archived (it is {task.state})")
        if task.archived_at:
            return task
        when = (now or datetime.now().astimezone()).isoformat(timespec="seconds")
        self.db.execute("UPDATE tasks SET archived_at=?, updated_at=datetime('now') WHERE id=?", (when, task_id))
        self.db.commit()
        self._sync(task_id)
        self.event(task_id, "archived", {"at": when})
        return self.get(task_id)  # type: ignore[return-value]

    def unarchive(self, task_id: str, now: datetime | None = None) -> Task:
        task = self.get(task_id)
        if not task:
            raise KeyError(task_id)
        if not task.archived_at:
            return task
        self.db.execute("UPDATE tasks SET archived_at=NULL, updated_at=datetime('now') WHERE id=?", (task_id,))
        self.db.commit()
        self._sync(task_id)
        self.event(task_id, "unarchived", {"was_archived_at": task.archived_at})
        return self.get(task_id)  # type: ignore[return-value]

    def update(self, task_id: str, **fields: Any) -> None:
        sets, args = [], []
        for k, v in fields.items():
            if k not in _COLS or k in ("id", "state", "archived_at"):   # archive() is the only way to archived_at
                raise ValueError(k)
            sets.append(f"{k}=?")
            args.append(json.dumps(v, ensure_ascii=False) if k in _JSON else v)
        self.db.execute(f"UPDATE tasks SET {', '.join(sets)}, updated_at=datetime('now') WHERE id=?", (*args, task_id))
        self.db.commit()
        self._sync(task_id)

    def event(self, task_id: str, kind: str, detail: dict | str | None = None) -> None:
        text = detail if isinstance(detail, str) or detail is None else json.dumps(detail, ensure_ascii=False)
        ts = _now()
        self.db.execute("INSERT INTO task_events (task_id, ts, kind, detail) VALUES (?, ?, ?, ?)",
                        (task_id, ts, kind, text))
        self.db.commit()
        truth.append_jsonl(self.folder(task_id) / "events.jsonl", {"ts": ts, "kind": kind, "detail": text})

    def events(self, task_id: str) -> list[dict]:
        rows = self.db.execute("SELECT ts, kind, detail FROM task_events WHERE task_id=? ORDER BY id", (task_id,))
        out = []
        for ts, kind, detail in rows:
            try:
                parsed = json.loads(detail) if detail else None
            except json.JSONDecodeError:
                parsed = detail
            out.append({"ts": ts, "kind": kind, "detail": parsed})
        return out

    def usage(self, task_id: str) -> dict[str, Any]:
        row = self.db.execute(
            """SELECT COUNT(*), COALESCE(SUM(input_tokens),0), COALESCE(SUM(output_tokens),0),
                      COALESCE(SUM(notional_usd),0), COALESCE(SUM(cost_usd),0) FROM model_usage WHERE task_id=?""",
            (task_id,)).fetchone()
        models = [r[0] for r in self.db.execute(
            "SELECT DISTINCT provider || '/' || model FROM model_usage WHERE task_id=?", (task_id,))]
        return {"calls": row[0], "input_tokens": row[1], "output_tokens": row[2], "notional_usd": round(row[3], 4),
                "billed_usd": round(row[4], 4), "models": models}

    def resumable(self) -> list[Task]:
        """Tasks interrupted mid-run (crash) or waiting in the queue, in priority order."""
        return [t for t in self.list() if t.state in ("RUNNING", "VERIFYING", "PLANNED", "BACKLOG")]
