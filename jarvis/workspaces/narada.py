"""Narada between lokas (PLAN.md 27.4, 27.5 item 6, 27.6 item 7): one office asks another for work.

A request goes through Jarvis and is logged. The asked office's lord takes it as an ordinary task in
its own workspace (law 4: its tools, its memory, its budget). When that task ends, only the result
crosses back: a short text and, if the task wrote one, the deliverable file, copied into the asking
office's inbox (data/workspaces/<from>/inbox/). No memory ever crosses.

Who may ask whom: the personal workspace may ask any office; a company may ask only the offices in
its `allies` list (workspace.yaml). A request is never deleted: it is archived (law 2), and only an
archived row may go, through `delete_forever`, Sachin's explicit, logged act.
"""

from __future__ import annotations

import logging
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jarvis.tasks.store import FINAL, Task, TaskStore
from jarvis.workspaces.model import PERSONAL, WorkspaceError
from jarvis.workspaces.store import WorkspaceStore

log = logging.getLogger(__name__)

STATES = ("requested", "running", "done", "failed", "declined")
OPEN = ("requested", "running")
INBOX_DIR = "inbox"
MAX_RESULT = 4000

_SCHEMA = """
CREATE TABLE IF NOT EXISTS loka_requests (
    id TEXT PRIMARY KEY,
    from_workspace TEXT NOT NULL,
    to_workspace TEXT NOT NULL,
    goal TEXT NOT NULL,
    task_id TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'requested',
    result TEXT,
    deliverable TEXT,
    source TEXT NOT NULL DEFAULT 'cli',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    archived_at TEXT
);
CREATE INDEX IF NOT EXISTS loka_requests_task ON loka_requests(task_id);
"""

_COLS = ("id", "from_workspace", "to_workspace", "goal", "task_id", "state", "result", "deliverable", "source",
         "created_at", "updated_at", "archived_at")


class NaradaRefused(WorkspaceError):
    """The request may not be made; the message says why and what would allow it."""


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Request:
    id: str
    from_workspace: str
    to_workspace: str
    goal: str
    task_id: str
    state: str
    result: str | None
    deliverable: str | None
    source: str
    created_at: str
    updated_at: str
    archived_at: str | None = None   # law 2: ended, never deleted

    @property
    def archived(self) -> bool:
        return bool(self.archived_at)

    @property
    def open(self) -> bool:
        return self.state in OPEN

    def line(self) -> str:
        first = (self.result or "").strip().splitlines()
        tail = f"  {first[0][:80]}" if first else ""
        flag = " (archived)" if self.archived else ""
        return f"{self.id} [{self.state}]{flag} {self.from_workspace} -> {self.to_workspace}: {self.goal[:60]} (task {self.task_id}){tail}"


def request_json(r: Request) -> dict[str, Any]:
    return {"id": r.id, "from": r.from_workspace, "to": r.to_workspace, "goal": r.goal, "task_id": r.task_id,
            "state": r.state, "result": r.result, "deliverable": r.deliverable, "source": r.source,
            "created_at": r.created_at, "updated_at": r.updated_at, "archived": r.archived, "line": r.line()}


class RequestStore:
    """The register of requests between offices. `home` is JARVIS_HOME (for workspace files and inboxes);
    `audit` is the audit log, when the caller has one (every power writes its rite there)."""

    def __init__(self, conn: sqlite3.Connection, home: Path, audit=None):
        self.db = conn
        self.home = home
        self.audit = audit
        self.db.executescript(_SCHEMA)
        self.db.commit()

    def _audit(self, event: str, **fields: Any) -> None:
        if self.audit is not None:
            self.audit.write(event, **fields)

    def _next_id(self) -> str:
        nums = [int(r[0][3:]) for r in self.db.execute("SELECT id FROM loka_requests") if r[0][3:].isdigit()]
        return f"lr-{(max(nums) + 1) if nums else 1:03d}"

    # ---- create ----

    def may_ask(self, from_ws: str, to_ws: str) -> None:
        """Both offices exist and are open, they differ, and `from_ws` may ask `to_ws`: personal may ask
        anyone; a company only its allies. Raises WorkspaceError (unknown) or NaradaRefused."""
        ws = WorkspaceStore(self.home)
        src = ws.get(from_ws)
        dst = ws.get(to_ws)
        if from_ws == to_ws:
            raise NaradaRefused(f"{from_ws} cannot ask itself: give another workspace")
        for w in (src, dst):
            if w.archived:
                raise NaradaRefused(f"workspace {w.slug!r} is archived (jarvis workspace unarchive {w.slug})")
        if src.slug != PERSONAL and to_ws not in src.allies:
            raise NaradaRefused(f"{from_ws} may not ask {to_ws}: add it to allies in workspace.yaml")

    def ask(self, from_ws: str, to_ws: str, goal: str, tasks: TaskStore, now: datetime | None = None,
            source: str = "cli") -> Request:
        """File the request and create its task in the asked office. The task's owner names the asker
        (narada:<from>) so the receipt and the Office page show where it came from."""
        goal = (goal or "").strip()
        if not goal:
            raise NaradaRefused("say what the other office should do")
        self.may_ask(from_ws, to_ws)
        now = now or _now()
        task = tasks.create(goal, title=f"Request from {from_ws}: {goal}", workspace=to_ws)
        tasks.update(task.id, owner=f"narada:{from_ws}")
        tasks.event(task.id, "loka_request", {"from": from_ws, "to": to_ws})
        rid = self._next_id()
        self.db.execute(
            "INSERT INTO loka_requests (id, from_workspace, to_workspace, goal, task_id, state, source, created_at, "
            "updated_at) VALUES (?, ?, ?, ?, ?, 'requested', ?, ?, ?)",
            (rid, from_ws, to_ws, goal, task.id, source, _iso(now), _iso(now)))
        self.db.commit()
        self._audit("loka_request_made", request_id=rid, **{"from": from_ws, "to": to_ws}, task_id=task.id,
                    goal=goal[:200], source=source)
        return self.get(rid)  # type: ignore[return-value]

    # ---- preserve ----

    def get(self, rid: str) -> Request | None:
        row = self.db.execute(f"SELECT {', '.join(_COLS)} FROM loka_requests WHERE id=?", (rid,)).fetchone()
        return Request(**dict(zip(_COLS, row))) if row else None

    def for_task(self, task_id: str) -> Request | None:
        """The open request a task answers, if it is one."""
        row = self.db.execute("SELECT id FROM loka_requests WHERE task_id=? AND state IN ('requested', 'running') "
                              "ORDER BY id", (task_id,)).fetchone()
        return self.get(row[0]) if row else None

    def list(self, workspace: str | None = None, include_archived: bool = False) -> list[Request]:
        """Requests from or to a workspace (all of them without one), oldest first."""
        where, args = [], []
        if workspace:
            where.append("(from_workspace=? OR to_workspace=?)")
            args += [workspace, workspace]
        if not include_archived:
            where.append("archived_at IS NULL")
        sql = "SELECT id FROM loka_requests" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY id"
        return [self.get(r[0]) for r in self.db.execute(sql, args)]  # type: ignore[misc]

    def _resolve(self, rid_or_task: str) -> Request:
        r = self.get(rid_or_task) or self.for_task(rid_or_task)
        if not r:
            raise WorkspaceError(f"no request {rid_or_task!r} (see: jarvis workspace requests)")
        return r

    def _set(self, rid: str, now: datetime, **fields: Any) -> Request:
        sets = ", ".join(f"{k}=?" for k in fields)
        self.db.execute(f"UPDATE loka_requests SET {sets}, updated_at=? WHERE id=?", (*fields.values(), _iso(now), rid))
        self.db.commit()
        return self.get(rid)  # type: ignore[return-value]

    def start(self, rid_or_task: str, now: datetime | None = None) -> Request:
        """The asked office has begun (its task is running)."""
        r = self._resolve(rid_or_task)
        if r.state != "requested":
            return r
        return self._set(r.id, now or _now(), state="running")

    def deliver(self, rid_or_task: str, task: Task, summary: str | None = None, deliverable: str | None = None,
                now: datetime | None = None) -> Request:
        """The task has ended: record the result and hand over the deliverable file alone. The file is
        copied from the task's own folder into data/workspaces/<from>/inbox/<task_id>-<filename>; nothing
        else of the asked office (memory, messages, tool runs) crosses."""
        r = self._resolve(rid_or_task)
        now = now or _now()
        if task.state == "COMPLETED":
            state = "done"
        elif task.state == "CANCELLED":
            state = "declined"
        else:
            state = "failed"
        result = (summary or "").strip() or (task.last_error or "").strip()
        if state == "declined" and not result:
            result = "cancelled by the asked office"
        copied: str | None = None
        if deliverable and state == "done":
            copied = self._hand_over(r, task, Path(deliverable))
        r = self._set(r.id, now, state=state, result=result[:MAX_RESULT] or None, deliverable=copied)
        self._audit("loka_request_delivered", request_id=r.id, **{"from": r.from_workspace, "to": r.to_workspace},
                    task_id=task.id, state=state, deliverable=copied, summary=result[:200])
        return r

    def _hand_over(self, r: Request, task: Task, src: Path) -> str | None:
        """Copy the deliverable into the asking office's inbox. Only a file inside the task's own folder
        may cross; anything else is refused and recorded, never copied."""
        tasks_root = (self.home / "data" / "tasks" / task.id).resolve()
        try:
            real = src.resolve(strict=True)
            real.relative_to(tasks_root)
        except (OSError, ValueError):
            self._audit("loka_request_deliverable_refused", request_id=r.id, task_id=task.id, path=str(src))
            return None
        inbox = self.home / "data" / "workspaces" / r.from_workspace / INBOX_DIR
        inbox.mkdir(parents=True, exist_ok=True)
        dest = inbox / f"{task.id}-{real.name}"
        shutil.copy2(real, dest)
        return str(dest)

    # ---- end ----

    def decline(self, rid_or_task: str, reason: str, now: datetime | None = None, source: str = "cli") -> Request:
        """The asked office (or Sachin) says no; the task stays as it is for the caller to cancel."""
        r = self._resolve(rid_or_task)
        if not r.open:
            raise WorkspaceError(f"request {r.id} is already {r.state}")
        r = self._set(r.id, now or _now(), state="declined", result=(reason or "declined").strip()[:MAX_RESULT])
        self._audit("loka_request_declined", request_id=r.id, **{"from": r.from_workspace, "to": r.to_workspace},
                    task_id=r.task_id, reason=(reason or "")[:200], source=source)
        return r

    def archive(self, rid: str, now: datetime | None = None, source: str = "cli") -> Request:
        r = self._resolve(rid)
        if r.archived:
            return r
        now = now or _now()
        r = self._set(r.id, now, archived_at=_iso(now))
        self._audit("loka_request_archived", request_id=r.id, source=source)
        return r

    def unarchive(self, rid: str, now: datetime | None = None, source: str = "cli") -> Request:
        r = self._resolve(rid)
        if not r.archived:
            return r
        r = self._set(r.id, now or _now(), archived_at=None)
        self._audit("loka_request_unarchived", request_id=r.id, source=source)
        return r

    def delete_forever(self, rid: str, source: str = "cli") -> bool:
        """Sachin's explicit, logged act only (law 2); an archived request only."""
        cur = self.db.execute("DELETE FROM loka_requests WHERE id=? AND archived_at IS NOT NULL", (rid,))
        self.db.commit()
        if cur.rowcount:
            self._audit("loka_request_deleted_forever", request_id=rid, source=source)
        return bool(cur.rowcount)


# ---- the hook the orchestrator calls ----

def _first_lines(path: Path, limit: int = 400) -> str:
    """The opening of a deliverable as a fallback summary: the first non-heading paragraph."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    para: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            if para:
                break
            continue
        para.append(s)
    return " ".join(para)[:limit]


def deliver_for_task(conn: sqlite3.Connection, home: Path, task: Task, summary: str | None, audit,
                     notifier=None, now: datetime | None = None) -> Request | None:
    """Called when a task's state changes. If the task answers a request: a running task marks the
    request running; a final one delivers the result (and the deliverable file named in the plan) and
    tells Sachin once through `notifier`. Never raises: the task's own ending comes first."""
    try:
        store = RequestStore(conn, home, audit)
        r = store.for_task(task.id)
        if r is None:
            return None
        if task.state not in FINAL:
            return store.start(r.id, now) if task.state == "RUNNING" else r
        filename = ((task.plan or {}).get("deliverable") or {}).get("filename")
        path = home / "data" / "tasks" / task.id / filename if filename else None
        deliverable = str(path) if path and path.is_file() else None
        text = summary or (task.last_error if task.state != "COMPLETED" else "") or (_first_lines(path) if deliverable else "")
        r = store.deliver(r.id, task, text, deliverable, now)
        if notifier is not None:
            try:
                what = (r.result or "").splitlines()[0][:200] if r.result else r.state
                notifier.send(f"Narada: {r.to_workspace} finished the request from {r.from_workspace}: {what}",
                              title="Jarvis")
            except Exception as e:  # a lost notification must not undo the delivery
                log.warning("narada notification failed: %s", e)
                if audit is not None:
                    audit.write("loka_request_notify_failed", request_id=r.id, error=str(e)[:200])
        return r
    except Exception as e:
        log.exception("narada delivery failed for %s", task.id)
        try:
            if audit is not None:
                audit.write("loka_request_delivery_failed", task_id=task.id, error=str(e)[:200])
        except Exception:
            pass
        return None


__all__ = ["RequestStore", "Request", "NaradaRefused", "deliver_for_task", "request_json", "STATES"]
