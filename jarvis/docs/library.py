"""DocLibrary: index and search approved documents in projects/<name>/docs/.

Only files Sachin put in a project's docs/ folder are indexed (PLAN.md section 7);
email attachments are never added on their own. Each chunk keeps its file, page,
section and the file date so answers can cite the source.

Search is the same as memory search (PLAN.md 6.4): FTS5 unicode61 for whole words
(Devanagari too) + FTS5 trigram for misspellings, merged with reciprocal rank fusion.

Privacy: every document has a class, P2 (private) by default. Sachin may mark a
document P1 in projects/<name>/docs_privacy.yaml or with `jarvis docs mark`. Callers
withhold chunks above their route's limit. P3 secrets found in a document are
redacted before anything is stored in the index.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

from jarvis.db import Store
from jarvis.docs.chunk import DEFAULT_CHARS, DEFAULT_OVERLAP, chunk_blocks
from jarvis.docs.extract import SUPPORTED, ExtractError, extract
from jarvis.memory.store import RRF_K, MemoryStore, _quote, _trigrams, _words
from jarvis.privacy import redact_p3
from jarvis.tools.files import is_secret_path

DOC_CLASSES = ("P0", "P1", "P2")
DEFAULT_CLASS = "P2"
PRIVACY_FILE = "docs_privacy.yaml"
MAX_FILE_BYTES = 50 * 1024 * 1024
_PROJECT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.\-]{0,63}$")

SCHEMA = """
CREATE TABLE IF NOT EXISTS doc_files (
    id INTEGER PRIMARY KEY,
    project TEXT NOT NULL,
    rel_path TEXT NOT NULL,
    sha256 TEXT,
    size INTEGER,
    mtime REAL,
    doc_date TEXT,
    privacy TEXT NOT NULL DEFAULT 'P2',
    chunks INTEGER NOT NULL DEFAULT 0,
    redacted INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'ok',
    error TEXT,
    indexed_at TEXT,
    UNIQUE(project, rel_path)
);
CREATE TABLE IF NOT EXISTS doc_chunks (
    id INTEGER PRIMARY KEY,
    file_id INTEGER NOT NULL,
    ordinal INTEGER NOT NULL,
    page INTEGER,
    section TEXT,
    text TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS doc_chunks_file ON doc_chunks(file_id);
CREATE VIRTUAL TABLE IF NOT EXISTS doc_words USING fts5(chunk_id UNINDEXED, text, tokenize='unicode61');
CREATE VIRTUAL TABLE IF NOT EXISTS doc_trigrams USING fts5(chunk_id UNINDEXED, text, tokenize='trigram');
"""


class DocError(ValueError):
    pass


@dataclass
class IndexReport:
    added: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)
    chunks: int = 0

    def summary(self) -> str:
        parts = [f"{len(self.added)} added", f"{len(self.updated)} updated", f"{len(self.unchanged)} unchanged",
                 f"{len(self.removed)} removed", f"{len(self.failed)} failed", f"{self.chunks} new chunks"]
        return ", ".join(parts)


@dataclass(frozen=True)
class DocHit:
    chunk_id: int
    project: str
    file: str
    page: int | None
    section: str
    doc_date: str
    privacy: str
    text: str
    score: float

    def citation(self) -> str:
        where = self.file
        if self.page is not None:
            where += f", p. {self.page}"
        elif self.section:
            where += f", section \"{self.section}\""
        return where


@dataclass(frozen=True)
class DocInfo:
    project: str
    file: str
    privacy: str
    chunks: int
    status: str
    doc_date: str
    error: str | None


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def check_project_name(name: str) -> str:
    if not _PROJECT_NAME.match(name) or ".." in name:
        raise DocError(f"invalid project name: {name!r}")
    return name


class DocLibrary:
    def __init__(self, home: Path, store: Store, chunk_chars: int = DEFAULT_CHARS,
                 overlap: int = DEFAULT_OVERLAP, max_file_bytes: int = MAX_FILE_BYTES):
        self.projects_root = home / "projects"
        self.db = store.conn
        self.chunk_chars = chunk_chars
        self.overlap = overlap
        self.max_file_bytes = max_file_bytes
        self.db.executescript(SCHEMA)
        self.db.commit()

    # ---- projects and privacy registry ----

    def projects(self) -> list[str]:
        if not self.projects_root.is_dir():
            return []
        return sorted(p.name for p in self.projects_root.iterdir()
                      if p.is_dir() and (p / "docs").is_dir() and _PROJECT_NAME.match(p.name))

    def docs_dir(self, project: str) -> Path:
        return self.projects_root / check_project_name(project) / "docs"

    def _privacy_path(self, project: str) -> Path:
        return self.projects_root / check_project_name(project) / PRIVACY_FILE

    def _privacy_map(self, project: str) -> dict[str, str]:
        path = self._privacy_path(project)
        if not path.exists():
            return {}
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        files = data.get("files") if isinstance(data, dict) else None
        if not isinstance(files, dict):
            return {}
        return {str(k).replace("\\", "/"): str(v) for k, v in files.items() if str(v) in DOC_CLASSES}

    def mark(self, project: str, file: str, privacy: str) -> str:
        """Set a document's privacy class in the project's registry file and the index."""
        if privacy not in DOC_CLASSES:
            raise DocError(f"class must be one of {', '.join(DOC_CLASSES)}")
        rel = self._relative(project, file)
        mapping = self._privacy_map(project)
        mapping[rel] = privacy
        path = self._privacy_path(project)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "# Privacy class per document in docs/ (private, not in git).\n"
            "# P2 = private (default; never sent to the cloud model). P1 = may be sent. P0 = public.\n"
            + yaml.safe_dump({"files": dict(sorted(mapping.items()))}, sort_keys=False, allow_unicode=True),
            encoding="utf-8")
        self.db.execute("UPDATE doc_files SET privacy=? WHERE project=? AND rel_path=?", (privacy, project, rel))
        self.db.commit()
        return rel

    def _relative(self, project: str, file: str) -> str:
        docs = self.docs_dir(project).resolve()
        candidate = Path(file)
        path = (candidate if candidate.is_absolute() else docs / candidate).resolve()
        if not path.is_relative_to(docs):
            raise DocError(f"{file} is not inside {project}/docs")
        if not path.is_file():
            raise DocError(f"no document {file} in project {project}")
        return path.relative_to(docs).as_posix()

    # ---- indexing ----

    def _candidates(self, docs: Path) -> list[Path]:
        root = docs.resolve()
        out = []
        for path in sorted(docs.rglob("*")):
            rel_parts = path.relative_to(docs).parts
            if any(p.startswith((".", "~$")) for p in rel_parts):
                continue  # hidden files, Office lock files
            if not path.is_file() or path.suffix.lower() not in SUPPORTED:
                continue
            real = path.resolve()
            if not real.is_relative_to(root) or is_secret_path(real):
                continue  # links out of docs/ and secret files are never indexed
            out.append(path)
        return out

    def index(self, project: str | None = None, force: bool = False) -> IndexReport:
        """Index new and changed files; drop removed ones. Unchanged files are skipped."""
        report = IndexReport()
        for name in ([check_project_name(project)] if project else self.projects()):
            self._index_project(name, report, force)
        return report

    def _index_project(self, project: str, report: IndexReport, force: bool) -> None:
        docs = self.docs_dir(project)
        privacy = self._privacy_map(project)
        seen: set[str] = set()
        for path in (self._candidates(docs) if docs.is_dir() else []):
            rel = path.relative_to(docs).as_posix()
            seen.add(rel)
            label = f"{project}/{rel}"
            cls = privacy.get(rel, DEFAULT_CLASS)
            stat = path.stat()
            row = self.db.execute("SELECT id, sha256, size, mtime, privacy FROM doc_files WHERE project=? AND rel_path=?",
                                  (project, rel)).fetchone()
            if row and row[4] != cls:
                self.db.execute("UPDATE doc_files SET privacy=? WHERE id=?", (cls, row[0]))
            if row and not force and row[2] == stat.st_size and row[3] == stat.st_mtime:
                report.unchanged.append(label)
                continue
            if stat.st_size > self.max_file_bytes:
                report.failed.append((label, f"larger than {self.max_file_bytes // (1024 * 1024)} MB"))
                continue
            digest = _sha256(path)
            if row and not force and row[1] == digest:
                self.db.execute("UPDATE doc_files SET mtime=?, size=? WHERE id=?", (stat.st_mtime, stat.st_size, row[0]))
                report.unchanged.append(label)
                continue
            try:
                blocks = extract(path)
                status, error = ("ok", None) if blocks else ("no_text", "no text layer (scanned? OCR comes in Phase 8)")
            except ExtractError as e:
                blocks, status, error = [], "error", str(e)
            chunks = chunk_blocks(blocks, self.chunk_chars, self.overlap)
            doc_date = datetime.fromtimestamp(stat.st_mtime, timezone.utc).date().isoformat()
            if row:
                self._drop_chunks(row[0])
                file_id = row[0]
                self.db.execute(
                    """UPDATE doc_files SET sha256=?, size=?, mtime=?, doc_date=?, privacy=?, status=?, error=?,
                       indexed_at=datetime('now') WHERE id=?""",
                    (digest, stat.st_size, stat.st_mtime, doc_date, cls, status, error, file_id))
            else:
                file_id = self.db.execute(
                    """INSERT INTO doc_files (project, rel_path, sha256, size, mtime, doc_date, privacy, status, error,
                       indexed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
                    (project, rel, digest, stat.st_size, stat.st_mtime, doc_date, cls, status, error)).lastrowid
            redacted = 0
            for c in chunks:
                text, n = redact_p3(c.text)
                redacted += n
                chunk_id = self.db.execute(
                    "INSERT INTO doc_chunks (file_id, ordinal, page, section, text) VALUES (?, ?, ?, ?, ?)",
                    (file_id, c.ordinal, c.page, c.section, text)).lastrowid
                searchable = f"{rel} {c.section}\n{text}".lower()
                self.db.execute("INSERT INTO doc_words (chunk_id, text) VALUES (?, ?)", (chunk_id, searchable))
                self.db.execute("INSERT INTO doc_trigrams (chunk_id, text) VALUES (?, ?)", (chunk_id, searchable))
            self.db.execute("UPDATE doc_files SET chunks=?, redacted=? WHERE id=?", (len(chunks), redacted, file_id))
            self.db.commit()
            report.chunks += len(chunks)
            if status == "error":  # kept in the index so it is retried only after the file changes
                report.failed.append((label, error or "error"))
            else:
                (report.updated if row else report.added).append(label)

        for file_id, rel in self.db.execute("SELECT id, rel_path FROM doc_files WHERE project=?", (project,)).fetchall():
            if rel not in seen:
                self._drop_chunks(file_id)
                self.db.execute("DELETE FROM doc_files WHERE id=?", (file_id,))
                report.removed.append(f"{project}/{rel}")
        self.db.commit()

    def _drop_chunks(self, file_id: int) -> None:
        ids = [r[0] for r in self.db.execute("SELECT id FROM doc_chunks WHERE file_id=?", (file_id,))]
        for chunk_id in ids:
            self.db.execute("DELETE FROM doc_words WHERE chunk_id=?", (chunk_id,))
            self.db.execute("DELETE FROM doc_trigrams WHERE chunk_id=?", (chunk_id,))
        self.db.execute("DELETE FROM doc_chunks WHERE file_id=?", (file_id,))

    def documents(self, project: str | None = None) -> list[DocInfo]:
        sql = "SELECT project, rel_path, privacy, chunks, status, doc_date, error FROM doc_files"
        args: tuple = ()
        if project:
            sql += " WHERE project=?"
            args = (project,)
        return [DocInfo(*r) for r in self.db.execute(sql + " ORDER BY project, rel_path", args)]

    # ---- search ----

    def search(self, query: str, project: str | None = None, k: int = 5) -> list[DocHit]:
        words = _words(query)
        if not words:
            return []
        where, extra = "", ()
        if project:
            where, extra = " AND f.project=?", (project,)
        ranked: dict[int, float] = {}

        word_rows = self.db.execute(
            f"""SELECT w.chunk_id FROM doc_words w JOIN doc_chunks c ON c.id = w.chunk_id
                JOIN doc_files f ON f.id = c.file_id
                WHERE doc_words MATCH ?{where} ORDER BY bm25(doc_words) LIMIT 50""",
            (" OR ".join(_quote(w) for w in words), *extra)).fetchall()
        for rank, (cid,) in enumerate(word_rows):
            ranked[int(cid)] = ranked.get(int(cid), 0.0) + 1.0 / (RRF_K + rank + 1)
        exact = {int(r[0]) for r in word_rows}

        grams = set().union(*(_trigrams(w) for w in words if len(w) >= 3))
        if grams:
            tri_rows = self.db.execute(
                f"""SELECT t.chunk_id, t.text FROM doc_trigrams t JOIN doc_chunks c ON c.id = t.chunk_id
                    JOIN doc_files f ON f.id = c.file_id
                    WHERE doc_trigrams MATCH ?{where} ORDER BY bm25(doc_trigrams) LIMIT 50""",
                (" OR ".join(_quote(g) for g in sorted(grams)), *extra)).fetchall()
            rank = 0
            for cid, text in tri_rows:
                cid = int(cid)
                if cid not in exact and not MemoryStore._fuzzy_match(words, text):
                    continue  # a few shared trigrams is not a match
                ranked[cid] = ranked.get(cid, 0.0) + 1.0 / (RRF_K + rank + 1)
                rank += 1

        hits: list[DocHit] = []
        for cid, score in sorted(ranked.items(), key=lambda kv: kv[1], reverse=True)[:k]:
            row = self.db.execute(
                """SELECT f.project, f.rel_path, c.page, c.section, f.doc_date, f.privacy, c.text
                   FROM doc_chunks c JOIN doc_files f ON f.id = c.file_id WHERE c.id=?""", (cid,)).fetchone()
            if row:
                hits.append(DocHit(cid, row[0], row[1], row[2], row[3] or "", row[4] or "", row[5], row[6], score))
        return hits
