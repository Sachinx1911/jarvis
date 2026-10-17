"""`jarvis rebuild` and `jarvis verify`: the index (SQLite) against the truth (files), PLAN.md 27.12.

The pralaya test: delete data/jarvis.db, run `rebuild`, and the tasks, schedules and triggers are
the same, because their truth lives in files (jarvis/core/truth.py). `verify` is the nightly
cross-check (27.12, "pathas"): files without rows, rows without files, rows that differ from their
file, field by field. A mismatch is a report, never a silent repair.

Rules (law 2):
- rebuild never deletes a file and never deletes a row. A row with no file is reported; with
  `prune=True` its content is first written out as its file (so nothing is lost) and reported.
- where a row and its file differ, the file wins and the difference is listed.
- a bad file is never half-loaded: it is skipped and reported.
- task events (data/tasks/<id>/events.jsonl) are restored with the task row; run and fire history
  stays what SQLite remembers (measurements, not truth).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jarvis.core import truth

_TABLE_SETUP = {
    # the stores own their DDL; opening them makes sure the tables and the newer columns exist
    "tasks": ("jarvis.tasks.store", "TaskStore"),
    "schedules": ("jarvis.proactive.scheduler", "ScheduleStore"),
    "triggers": ("jarvis.proactive.triggers", "TriggerStore"),
}


@dataclass
class Difference:
    kind: str
    id: str
    fields: dict[str, tuple[Any, Any]]   # field -> (file value, row value)

    def line(self) -> str:
        parts = ", ".join(f"{k}: file={_short(v[0])} row={_short(v[1])}" for k, v in sorted(self.fields.items()))
        return f"{self.kind} {self.id} differs: {parts}"


@dataclass
class Report:
    action: str                                   # "verify" | "rebuild" | "rebuild (dry run)"
    counted: dict[str, int] = field(default_factory=dict)        # kind -> rows checked
    created: list[tuple[str, str]] = field(default_factory=list)  # rows made from files
    updated: list[Difference] = field(default_factory=list)       # rows corrected from their file
    differing: list[Difference] = field(default_factory=list)     # verify only: left as they are
    files_without_rows: list[tuple[str, str]] = field(default_factory=list)
    rows_without_files: list[tuple[str, str]] = field(default_factory=list)
    written_out: list[tuple[str, str]] = field(default_factory=list)   # prune: orphan rows given a file
    events_restored: int = 0
    problems: list[str] = field(default_factory=list)   # unreadable files

    @property
    def ok(self) -> bool:
        return not (self.differing or self.files_without_rows or self.rows_without_files or self.problems)

    def counts(self) -> dict[str, int]:
        return {"checked": sum(self.counted.values()), "created": len(self.created), "updated": len(self.updated),
                "differing": len(self.differing), "files_without_rows": len(self.files_without_rows),
                "rows_without_files": len(self.rows_without_files), "written_out": len(self.written_out),
                "events_restored": self.events_restored, "problems": len(self.problems)}

    def summary(self) -> str:
        """One line for the nightly review."""
        if self.ok:
            return "truth check: ok"
        n = len(self.differing) + len(self.files_without_rows) + len(self.rows_without_files) + len(self.problems)
        return f"truth check: {n} difference(s), run jarvis verify"

    def lines(self) -> list[str]:
        out = [f"{self.action}: " + ", ".join(f"{k} {v}" for k, v in sorted(self.counted.items()))]
        out += [f"  created {k} {i} from its file" for k, i in self.created]
        out += [f"  corrected {d.line()}" for d in self.updated]
        out += [f"  {d.line()}" for d in self.differing]
        out += [f"  file without row: {k} {i}" for k, i in self.files_without_rows]
        out += [f"  row without file: {k} {i}" for k, i in self.rows_without_files]
        out += [f"  wrote {k} {i} out to its file (the row had none)" for k, i in self.written_out]
        if self.events_restored:
            out.append(f"  restored {self.events_restored} task event(s)")
        out += [f"  problem: {p}" for p in self.problems]
        out.append("ok" if self.ok else "not ok")
        return out


def _short(value: Any, limit: int = 40) -> str:
    text = repr(value)
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _conn(store: Any) -> sqlite3.Connection:
    return store if isinstance(store, sqlite3.Connection) else store.conn


def _ensure_tables(home: Path, store: Any, kinds: tuple[str, ...]) -> None:
    import importlib

    conn = _conn(store)
    for kind in kinds:
        module, cls = _TABLE_SETUP[kind]
        klass = getattr(importlib.import_module(module), cls)
        if kind == "tasks":
            if not isinstance(store, sqlite3.Connection):
                klass(store, Path(home) / "data" / "tasks")
        else:
            klass(conn, Path(home))


def _rows(conn: sqlite3.Connection, spec: truth.Spec) -> dict[str, dict[str, Any]]:
    have = {r[1] for r in conn.execute(f"PRAGMA table_info({spec.table})")}
    cols = [c for c in spec.cols if c in have]
    if "id" not in cols:
        return {}
    out = {}
    for row in conn.execute(f"SELECT {', '.join(cols)} FROM {spec.table}"):
        data = dict(zip(cols, row))
        out[data["id"]] = spec.record_of_row(data)
    return out


def _diff(file_rec: dict[str, Any], row_rec: dict[str, Any], spec: truth.Spec) -> dict[str, tuple[Any, Any]]:
    fields = {}
    for col in spec.cols:
        if col in spec.skip:
            continue
        a, b = file_rec.get(col), row_rec.get(col)
        if a != b:
            fields[col] = (a, b)
    return fields


def _event_count(conn: sqlite3.Connection, task_id: str) -> int:
    return conn.execute("SELECT COUNT(*) FROM task_events WHERE task_id=?", (task_id,)).fetchone()[0]


def _compare(home: Path, conn: sqlite3.Connection, kind: str, report: Report):
    """Shared by verify and rebuild: (files, rows, both-and-different)."""
    spec = truth.SPECS[kind]
    files = truth.list_truth(home, kind, report.problems)
    rows = _rows(conn, spec)
    report.counted[kind] = len(rows)
    differing = []
    for rid in sorted(files):
        if rid in rows:
            fields = _diff(files[rid], rows[rid], spec)
            if fields:
                differing.append(Difference(kind, rid, fields))
    return files, rows, differing


def verify(home: Path, store: Any, kinds: tuple[str, ...] = truth.KINDS) -> Report:
    """Read-only: what the index says against what the files say."""
    home = Path(home)
    conn = _conn(store)
    report = Report("verify")
    for kind in kinds:
        files, rows, differing = _compare(home, conn, kind, report)
        report.differing += differing
        report.files_without_rows += [(kind, rid) for rid in sorted(files) if rid not in rows]
        report.rows_without_files += [(kind, rid) for rid in sorted(rows) if rid not in files]
        if kind == "tasks":
            for rid in sorted(files):
                if rid in rows:
                    on_file = len(truth.read_events(home, rid, report.problems))
                    in_db = _event_count(conn, rid)
                    if on_file > in_db:
                        report.differing.append(Difference(kind, rid, {"events": (on_file, in_db)}))
    return report


def rebuild(home: Path, store: Any, kinds: tuple[str, ...] = truth.KINDS, dry_run: bool = False,
            prune: bool = False) -> Report:
    """Recreate missing rows from their files; where both exist and differ, the file wins.
    Never deletes anything. `prune` writes an orphan row out as its file (nothing is lost)."""
    home = Path(home)
    conn = _conn(store)
    report = Report("rebuild (dry run)" if dry_run else "rebuild")
    if not dry_run:
        _ensure_tables(home, store, kinds)
    for kind in kinds:
        spec = truth.SPECS[kind]
        files, rows, differing = _compare(home, conn, kind, report)
        have = {r[1] for r in conn.execute(f"PRAGMA table_info({spec.table})")}
        for rid in sorted(files):
            if rid in rows:
                continue
            report.created.append((kind, rid))
            if dry_run:
                continue
            row = {k: v for k, v in spec.row_of_record(files[rid]).items() if k in have}
            cols = list(row)
            conn.execute(f"INSERT INTO {spec.table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                         tuple(row[c] for c in cols))
        for d in differing:
            report.updated.append(d)
            if dry_run:
                continue
            row = {k: v for k, v in spec.row_of_record(files[d.id]).items() if k in have and k in d.fields}
            if row:
                sets = ", ".join(f"{k}=?" for k in row)
                conn.execute(f"UPDATE {spec.table} SET {sets} WHERE id=?", (*row.values(), d.id))
        for rid in sorted(rows):
            if rid in files:
                continue
            if prune:
                report.written_out.append((kind, rid))
                if not dry_run:
                    if kind == "tasks":
                        truth.write_json(truth.truth_path(home, kind, rid),
                                         {**rows[rid], "truth_version": truth.TRUTH_VERSION})
                    else:
                        truth.write_truth(home, kind, rid, rows[rid])
            else:
                report.rows_without_files.append((kind, rid))
        if kind == "tasks":
            for rid in sorted(files):
                events = truth.read_events(home, rid, report.problems)
                in_db = 0 if rid not in rows else _event_count(conn, rid)
                missing = events[in_db:] if len(events) > in_db else []
                report.events_restored += len(missing)
                if dry_run:
                    continue
                for e in missing:
                    conn.execute("INSERT INTO task_events (task_id, ts, kind, detail) VALUES (?, ?, ?, ?)",
                                 (rid, e.get("ts"), e.get("kind", "?"), e.get("detail")))
        if not dry_run:
            conn.commit()
    return report


__all__ = ["Difference", "Report", "rebuild", "verify"]
