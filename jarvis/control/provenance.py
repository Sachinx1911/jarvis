"""File provenance: taint that survives being written to disk (research notes P0 #3).

Without it, taint is laundered through files: a tainted session (or agent) writes web-derived
text into a file, a later clean session reads the file and treats it as trusted. Rules:

- every file written by a tool gets a row in file_provenance (path, sha256, tainted, source);
  it is tainted when the writing session/agent was tainted;
- reading (or listing) a file taints the reader when its path is recorded as tainted, when its
  current content hash matches any tainted record (so a moved or copied file stays tainted), or
  when it lies in an untrusted zone: task folders and session folders, where agents write
  research, reports and browser downloads.

The table is owned by this module (created on first use), not by jarvis/db.py.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

SCHEMA = (
    # Append-only: a tainted content hash is never forgotten, so a copy made of a tainted file
    # stays tainted even after the original path is overwritten with clean text.
    """CREATE TABLE IF NOT EXISTS file_provenance (
        id INTEGER PRIMARY KEY,
        path TEXT NOT NULL,
        sha256 TEXT NOT NULL,
        tainted INTEGER NOT NULL,
        source TEXT,
        ts TEXT NOT NULL DEFAULT (datetime('now'))
    )""",
    "CREATE INDEX IF NOT EXISTS file_provenance_path ON file_provenance(path)",
    "CREATE INDEX IF NOT EXISTS file_provenance_sha ON file_provenance(sha256)",
)
MAX_HASH_BYTES = 20_000_000


def untrusted_zones(home: Path) -> list[Path]:
    """Folders whose files are untrusted by location: agents write web-derived research,
    reports and browser downloads there (data/tasks/<id>/, data/sessions/<id>/)."""
    return [home / "data" / "tasks", home / "data" / "sessions"]


def file_sha256(path: Path) -> str | None:
    try:
        if not path.is_file() or path.stat().st_size > MAX_HASH_BYTES:
            return None
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _key(path: Path) -> str:
    return str(path.expanduser().resolve())


class Provenance:
    def __init__(self, conn: sqlite3.Connection, zones: list[Path] | None = None):
        self.conn = conn
        self.zones = [z.expanduser().resolve() for z in (zones or [])]
        for stmt in SCHEMA:
            conn.execute(stmt)
        conn.commit()

    def _latest(self, key: str) -> tuple | None:
        return self.conn.execute("SELECT sha256, tainted, source FROM file_provenance WHERE path=? "
                                 "ORDER BY id DESC LIMIT 1", (key,)).fetchone()

    def record(self, path: Path, tainted: bool, source: str) -> None:
        sha = file_sha256(path)
        if sha is None:
            return
        key = _key(path)
        last = self._latest(key)
        if last and last[0] == sha and (last[1] or not tainted):
            return  # same content: a clean no-op write never launders a tainted record
        self.conn.execute("INSERT INTO file_provenance (path, sha256, tainted, source) VALUES (?, ?, ?, ?)",
                          (key, sha, int(tainted), source))
        self.conn.commit()

    def why_tainted(self, path: Path) -> str | None:
        """Why reading this file must taint the reader, or None if it is clean."""
        p = path.expanduser().resolve()
        for z in self.zones:
            if p == z or p.is_relative_to(z):
                return "it is in a task or session folder, where agents save web-derived files"
        row = self._latest(_key(p))
        if row and row[1]:
            return f"it was written from untrusted input ({row[2]})"
        if p.is_file():
            sha = file_sha256(p)
            if sha:
                hit = self.conn.execute("SELECT source FROM file_provenance WHERE sha256=? AND tainted=1 LIMIT 1",
                                        (sha,)).fetchone()
                if hit:
                    return f"its content matches a file written from untrusted input ({hit[0]})"
        return None

    def folder_tainted(self, folder: Path, limit: int = 200) -> str | None:
        """Listing a folder shows file names, which can be attacker-chosen (downloads)."""
        why = self.why_tainted(folder)
        if why:
            return why
        try:
            children = sorted(folder.iterdir())[:limit]
        except OSError:
            return None
        for child in children:
            if child.is_file():
                why = self.why_tainted(child)
                if why:
                    return f"{child.name}: {why}"
        return None
