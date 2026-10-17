"""File truth (PLAN.md 27.1 law 2, 27.8 decision 10, 27.12): the truth of a task, a schedule and a
trigger is a plain JSON file under the data folder; the SQLite rows are an index that can be
rebuilt from the files (`jarvis rebuild`) and checked against them (`jarvis verify`).

Where the files live:
- tasks      -> data/tasks/<id>/task.json   (the task folder already holds receipt.md; events go to
                data/tasks/<id>/events.jsonl, append-only, so a rebuild restores them too)
- schedules  -> data/schedules/<id>.json
- triggers   -> data/triggers/<id>.json

Run and fire history (sched_runs, trig_fires, trig_seen, model_usage) stays in SQLite only: they are
measurements of what happened (law 7), not the thing itself; the run receipts already live as
markdown files next to the schedule and trigger output. A schedule's or trigger's own last_* fields
are part of its row and so of its file.

One canonical form (27.12, "exactness"): UTF-8, sorted keys, indent 2, non-ASCII kept as is, so two
copies of the same record are byte-identical and a diff means a change. Writes are atomic (temp
file + replace). Nothing here deletes a file except `remove_truth`, which only `delete_forever` in a
store may call (law 2: Sachin's explicit, logged act).
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

TRUTH_VERSION = 1


@dataclass(frozen=True)
class Spec:
    """How one kind maps between its table row and its file record."""
    kind: str
    table: str
    cols: tuple[str, ...]            # every column of the row that is truth (in table order)
    json_cols: frozenset[str]        # stored as JSON text in the row, as objects in the file
    bool_cols: frozenset[str]        # stored as 0/1 in the row, as true/false in the file
    skip: frozenset[str] = frozenset()   # row columns that are not truth (locks); never in the file

    def record_of_row(self, row: dict[str, Any]) -> dict[str, Any]:
        """The row as its canonical file record."""
        rec: dict[str, Any] = {}
        for col in self.cols:
            if col in self.skip:
                continue
            value = row.get(col)
            if col in self.json_cols:
                if isinstance(value, str):
                    try:
                        value = json.loads(value) if value else {}
                    except json.JSONDecodeError:
                        pass
                elif value is None:
                    value = {}
            elif col in self.bool_cols:
                value = bool(value)
            rec[col] = value
        return rec

    def row_of_record(self, rec: dict[str, Any]) -> dict[str, Any]:
        """The file record as row values, ready for INSERT or UPDATE."""
        row: dict[str, Any] = {}
        for col in self.cols:
            if col in self.skip or col not in rec:
                continue
            value = rec[col]
            if col in self.json_cols and not isinstance(value, str):
                value = json.dumps(value if value is not None else {}, ensure_ascii=False)
            elif col in self.bool_cols:
                value = int(bool(value))
            row[col] = value
        return row


SPECS: dict[str, Spec] = {
    "tasks": Spec(
        "tasks", "tasks",
        ("id", "title", "goal", "state", "project", "priority", "deadline", "owner", "budget", "plan",
         "checkpoint", "last_error", "retries", "current_step", "created_at", "updated_at", "workspace",
         "archived_at"),
        frozenset({"budget", "plan", "checkpoint"}), frozenset()),
    "schedules": Spec(
        "schedules", "sched_schedules",
        ("id", "name", "kind", "target", "input", "cron", "timezone", "output", "budget", "misfire_grace_s",
         "enabled", "source", "created_at", "updated_at", "next_run_at", "last_run_at", "last_status",
         "last_detail", "last_output", "running_since", "workspace", "archived_at"),
        frozenset({"budget"}), frozenset({"enabled"}), frozenset({"running_since"})),
    "triggers": Spec(
        "triggers", "trig_triggers",
        ("id", "name", "source", "condition", "action", "target", "input", "output", "every_s", "cooldown_s",
         "enabled", "created_by", "description", "created_at", "updated_at", "state", "last_poll_at",
         "next_poll_at", "last_status", "last_detail", "last_fired_at", "failures", "workspace", "archived_at"),
        frozenset({"condition", "state"}), frozenset({"enabled"})),
}
KINDS = tuple(SPECS)


# ---------------------------------------------------------------- paths


def home_of(conn: sqlite3.Connection) -> Path | None:
    """JARVIS_HOME derived from the connection's main database (data/jarvis.db -> home).
    None for an in-memory or temporary database: then there is no file truth to write."""
    try:
        for _, name, file in conn.execute("PRAGMA database_list"):
            if name == "main" and file:
                db = Path(file)
                if db.parent.name == "data":
                    return db.parent.parent
                return None
    except sqlite3.Error:
        return None
    return None


def truth_dir(home: Path, kind: str) -> Path:
    if kind not in SPECS:
        raise KeyError(kind)
    return Path(home) / "data" / kind


def truth_path(home: Path, kind: str, id: str) -> Path:
    if kind == "tasks":
        return truth_dir(home, kind) / id / "task.json"
    return truth_dir(home, kind) / f"{id}.json"


def events_path(home: Path, task_id: str) -> Path:
    return truth_dir(home, "tasks") / task_id / "events.jsonl"


# ---------------------------------------------------------------- read and write


def dumps(record: dict[str, Any]) -> str:
    return json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def write_json(path: Path, record: dict[str, Any]) -> Path:
    """Atomic: the whole file appears or nothing does (law 2, born whole)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(dumps(record), encoding="utf-8")
    for attempt in range(5):  # Windows: a reader may hold the target for a moment
        try:
            os.replace(tmp, path)
            return path
        except PermissionError:
            if attempt == 4:
                tmp.unlink(missing_ok=True)
                raise
            time.sleep(0.05 * (attempt + 1))
    return path


def write_truth(home: Path, kind: str, id: str, record: dict[str, Any]) -> Path:
    return write_json(truth_path(home, kind, id), {**record, "truth_version": TRUTH_VERSION})


def read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: not a JSON object")
    return data


def read_truth(home: Path, kind: str, id: str) -> dict[str, Any] | None:
    """The record as the file holds it (without the format marker), or None when there is no file."""
    rec = read_json(truth_path(home, kind, id))
    if rec is None:
        return None
    rec.pop("truth_version", None)
    return rec


def list_truth(home: Path, kind: str, problems: list[str] | None = None) -> dict[str, dict[str, Any]]:
    """Every readable record of a kind, by id. A bad file is never half-loaded (law 2): it is skipped
    and named in `problems` when a list is given."""
    folder = truth_dir(home, kind)
    out: dict[str, dict[str, Any]] = {}
    if not folder.exists():
        return out
    if kind == "tasks":
        paths = sorted(p / "task.json" for p in folder.iterdir() if p.is_dir() and (p / "task.json").exists())
    else:
        paths = sorted(p for p in folder.glob("*.json") if p.is_file() and not p.name.startswith("."))
    for path in paths:
        try:
            rec = read_json(path)
        except (OSError, ValueError) as e:
            if problems is not None:
                problems.append(f"{path}: {e}")
            continue
        if rec is None:
            continue
        rec.pop("truth_version", None)
        rid = rec.get("id")
        expected = path.parent.name if kind == "tasks" else path.stem
        if not isinstance(rid, str) or rid != expected:
            if problems is not None:
                problems.append(f"{path}: id {rid!r} does not match its file name {expected!r}")
            continue
        out[rid] = rec
    return out


def remove_truth(home: Path, kind: str, id: str) -> bool:
    """The one deletion of a truth file. Only a store's `delete_forever` may call it."""
    path = truth_path(home, kind, id)
    if path.exists():
        path.unlink()
        return True
    return False


# ---------------------------------------------------------------- task events (append-only)


def append_jsonl(path: Path, item: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")


def append_event(home: Path, task_id: str, event: dict[str, Any]) -> None:
    append_jsonl(events_path(home, task_id), event)


def read_events(home: Path, task_id: str, problems: list[str] | None = None) -> list[dict[str, Any]]:
    path = events_path(home, task_id)
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as e:
            if problems is not None:
                problems.append(f"{path}:{n}: {e}")
            continue
        if isinstance(item, dict):
            out.append(item)
    return out


__all__ = ["KINDS", "SPECS", "Spec", "TRUTH_VERSION", "append_event", "append_jsonl", "events_path", "home_of", "list_truth",
           "read_events", "read_truth", "remove_truth", "truth_dir", "truth_path", "write_json", "write_truth"]
