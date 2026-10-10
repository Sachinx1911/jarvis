"""MemoryStore: markdown files are the source of truth, SQLite is only an index.

Search (PLAN.md 6.4): FTS5 unicode61 (whole words, Devanagari too) + FTS5 trigram
(misspellings), merged with reciprocal rank fusion, active memories only, a minimum
match gate (0 to k results, not always k) and a small recency boost.
Vector search is deferred (decided 2026-10-10).

Retrieval improvements (research 2026-10-10, topic 4), each switchable for the memory eval:
- script_forms: the index also holds a canonical romanized key of every word, and the query
  is expanded the same way, so Devanagari and romanized Marathi match each other
  (jarvis.memory.translit). It also fixes Devanagari word search: FTS5 unicode61 splits
  Devanagari words at every vowel sign, the romanized key is one whole word.
- time_aware: a date range in the question (jarvis.memory.timefilter) adds a ranked list of
  the matching memories saved in that range to the rank fusion; the time words themselves
  are not used as search words.
"""

from __future__ import annotations

import json
import math
import shutil
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from jarvis.db import Store
from jarvis.memory.model import TYPE_DIRS, Memory, slugify
from jarvis.memory.timefilter import DateRange, extract_range
from jarvis.memory.translit import canonical_roman, expand_words, index_variants, words as _tokens
from jarvis.privacy import find_p3

RRF_K = 60
MIN_TRIGRAM_COVERAGE = 0.5   # fuzzy-only hits must share half of a query word's trigrams
MEMORY_INDEX_MAX_LINES = 200
AUTO = "auto"
TRASH_DIR = ".trash"  # memory/.trash: deleted memories (never hard-deleted silently; restorable)

# Very common words that carry no meaning for search (English + romanized Marathi).
_STOP_RAW = {
    "the", "a", "an", "is", "are", "was", "to", "of", "and", "or", "in", "on", "for", "my", "me", "i",
    "you", "it", "what", "how", "do", "does", "please", "jarvis", "sir",
    "ahe", "aahe", "ahes", "kay", "ka", "mi", "maza", "majha", "mazi", "tu", "la", "na", "ani", "pan",
    "he", "te", "ha", "ti", "kasa", "kashi", "sang", "sanga",
    # question and reporting words that every memory question carries
    "did", "tell", "told", "say", "said", "about", "which", "when", "where", "who", "your",
    "madhe", "madhye", "kuthe", "kevha", "kadhi", "sangitla", "sangitle", "sangitli", "hota", "hoti", "hote",
}
STOPWORDS = _STOP_RAW | {canonical_roman(w) for w in _STOP_RAW}


class MemoryRejected(ValueError):
    pass


@dataclass
class SearchHit:
    memory: Memory
    score: float


def _words(text: str) -> list[str]:
    """Search words: Devanagari words kept whole (not split at vowel signs), stopwords out."""
    return [w for w in _tokens(text) if w not in STOPWORDS]


def _trigrams(word: str) -> set[str]:
    return {word[i:i + 3] for i in range(len(word) - 2)}


def _quote(term: str) -> str:
    return '"' + term.replace('"', '""') + '"'


class MemoryStore:
    def __init__(self, home: Path, store: Store, script_forms: bool = True, time_aware: bool = True):
        self.root = home / "memory"
        self.store = store
        self.db = store.conn
        self.script_forms = script_forms   # romanized keys in the index and the query (translit)
        self.time_aware = time_aware       # date ranges in questions boost memories saved then
        for sub in TYPE_DIRS.values():
            (self.root / sub).mkdir(parents=True, exist_ok=True)

    # ---- files ----

    def _next_id(self) -> str:
        nums = [int(r[0][2:]) for r in self.db.execute("SELECT id FROM memory_index") if r[0][2:].isdigit()]
        for path in self.root.rglob("m-*.md"):
            head = path.name[2:6]
            if head.isdigit():
                nums.append(int(head))
        return f"m-{(max(nums) + 1) if nums else 1:04d}"

    def _path_for(self, mem: Memory) -> Path:
        return self.root / TYPE_DIRS[mem.type] / f"{mem.id}-{slugify(mem.name)}.md"

    def _write(self, mem: Memory) -> Path:
        old = self._indexed_path(mem.id)
        path = self._path_for(mem)
        path.write_text(mem.to_markdown(), encoding="utf-8")
        if old and old != path and old.exists():
            old.unlink()  # type or name changed: the file moved
        self._index(mem, path)
        return path

    def _indexed_path(self, memory_id: str) -> Path | None:
        row = self.db.execute("SELECT path FROM memory_index WHERE id=?", (memory_id,)).fetchone()
        return Path(row[0]) if row else None

    # ---- index ----

    def _index(self, mem: Memory, path: Path) -> None:
        self.db.execute("DELETE FROM memory_index WHERE id=?", (mem.id,))
        self.db.execute("DELETE FROM memory_words WHERE id=?", (mem.id,))
        self.db.execute("DELETE FROM memory_trigrams WHERE id=?", (mem.id,))
        self.db.execute(
            """INSERT INTO memory_index (id, path, type, status, name, subject, scope, sensitivity, valid_from)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (mem.id, str(path), mem.type, mem.status, mem.name, mem.subject, mem.scope, mem.sensitivity, mem.valid_from),
        )
        text = mem.search_text().lower()
        if self.script_forms:
            extra = index_variants(text)
            text = f"{text}\n{extra}" if extra else text
        self.db.execute("INSERT INTO memory_words (id, text) VALUES (?, ?)", (mem.id, text))
        self.db.execute("INSERT INTO memory_trigrams (id, text) VALUES (?, ?)", (mem.id, text))
        self.db.commit()

    def reindex(self) -> int:
        """Rebuild the index from the markdown files (after manual edits)."""
        self.db.execute("DELETE FROM memory_index")
        self.db.execute("DELETE FROM memory_words")
        self.db.execute("DELETE FROM memory_trigrams")
        count = 0
        for path in sorted(self.root.rglob("m-*.md")):
            if TRASH_DIR in path.relative_to(self.root).parts:
                continue  # deleted memories stay out of the index until restored
            try:
                mem = Memory.from_markdown(path.read_text(encoding="utf-8"))
            except ValueError:
                continue
            self._index(mem, path)
            count += 1
        self.write_memory_md()
        return count

    # ---- public API ----

    def save(self, mem: Memory) -> Memory:
        mem.validate()
        secrets = find_p3(mem.search_text())
        if secrets or mem.sensitivity == "secret":
            raise MemoryRejected(f"contains secret data ({', '.join(secrets) or 'marked secret'}); never stored")
        if mem.source == "inferred" and mem.confidence == "high":
            mem.confidence = "medium"  # inferred memories stay at or below medium until confirmed
        if not mem.id:
            mem.id = self._next_id()
        self._write(mem)
        self.write_memory_md()
        return mem

    def get(self, memory_id: str) -> Memory | None:
        path = self._indexed_path(memory_id)
        if not path or not path.exists():
            return None
        return Memory.from_markdown(path.read_text(encoding="utf-8"))

    def list(self, type: str | None = None, status: str | None = "active") -> list[Memory]:
        sql, args = "SELECT id FROM memory_index WHERE 1=1", []
        if type:
            sql += " AND type=?"
            args.append(type)
        if status:
            sql += " AND status=?"
            args.append(status)
        out = [self.get(r[0]) for r in self.db.execute(sql + " ORDER BY id", args)]
        return [m for m in out if m]

    def supersede(self, old_id: str, new: Memory) -> Memory:
        old = self.get(old_id)
        if not old:
            raise KeyError(old_id)
        if new.subject == "":
            new.subject = old.subject
        saved = self.save(new)
        old.status = "superseded"
        old.superseded_by = saved.id
        old.valid_until = date.today().isoformat()
        self._write(old)
        self.write_memory_md()
        return saved

    def update(self, mem: Memory) -> Memory:
        if not mem.id or not self.get(mem.id):
            raise KeyError(mem.id)
        mem.validate()
        if find_p3(mem.search_text()):
            raise MemoryRejected("contains secret data; never stored")
        self._write(mem)
        self.write_memory_md()
        return mem

    def archive(self, memory_id: str) -> Memory:
        mem = self.get(memory_id)
        if not mem:
            raise KeyError(memory_id)
        mem.status = "archived"
        self._write(mem)
        self.write_memory_md()
        return mem

    # ---- trash (delete = move the file to memory/.trash and drop it from the index) ----

    @property
    def trash_dir(self) -> Path:
        return self.root / TRASH_DIR

    def trash(self, memory_id: str) -> Path:
        """Delete a memory: its file moves to memory/.trash (restorable), the index forgets it.
        Its id is never reused (_next_id also counts trashed files)."""
        path = self._indexed_path(memory_id)
        if not path or not path.exists():
            raise KeyError(memory_id)
        self.trash_dir.mkdir(parents=True, exist_ok=True)
        dest = self.trash_dir / f"{path.stem}.{datetime.now():%Y%m%d-%H%M%S%f}.md"  # keeps the m-NNNN prefix
        shutil.move(str(path), str(dest))
        for table in ("memory_index", "memory_words", "memory_trigrams"):
            self.db.execute(f"DELETE FROM {table} WHERE id=?", (memory_id,))
        self.db.commit()
        self.write_memory_md()
        return dest

    def trashed(self) -> list[tuple[str, Memory]]:
        """(file name, memory) for every memory in the trash, newest first."""
        if not self.trash_dir.exists():
            return []
        out = []
        for path in sorted(self.trash_dir.glob("*.md"), key=lambda p: p.stem.rsplit(".", 1)[-1], reverse=True):
            try:
                out.append((path.name, Memory.from_markdown(path.read_text(encoding="utf-8"))))
            except ValueError:
                continue
        return out

    def restore(self, file_name: str) -> Memory:
        """Bring a trashed memory back under its old id (refused if that id is in use again)."""
        if Path(file_name).name != file_name or not file_name.endswith(".md"):
            raise KeyError(file_name)
        src = self.trash_dir / file_name
        if not src.is_file():
            raise KeyError(file_name)
        mem = Memory.from_markdown(src.read_text(encoding="utf-8"))
        if self._indexed_path(mem.id):
            raise ValueError(f"{mem.id} is in use by another memory")
        mem.validate()
        self._write(mem)
        src.unlink()
        self.write_memory_md()
        return mem

    def mark_used(self, memory_id: str) -> None:
        mem = self.get(memory_id)
        if mem:
            mem.use_count += 1
            mem.last_used = date.today().isoformat()
            self._write(mem)

    def export(self, dest: Path) -> int:
        mems = self.list(status=None)
        dest.write_text(json.dumps([m.__dict__ for m in mems], ensure_ascii=False, indent=2), encoding="utf-8")
        return len(mems)

    # ---- search ----

    def query_words(self, query: str, time_range: DateRange | None = None) -> list[str]:
        """The search words of a query: stopwords and time words out, other-script keys in."""
        words = _words(query)
        if time_range is not None:
            words = [w for w in words if w not in time_range.words]
        if self.script_forms:
            words = expand_words(words, STOPWORDS)
        return words

    def resolve_range(self, query: str, time_range: DateRange | str | None, today: date | None = None) -> DateRange | None:
        if time_range == AUTO:
            return extract_range(query, today or date.today()) if self.time_aware else None
        return time_range if self.time_aware else None  # type: ignore[return-value]

    def search(self, query: str, k: int = 5, include_sensitive: bool = True, scope: str | None = None,
               time_range: DateRange | str | None = AUTO, today: date | None = None) -> list[SearchHit]:
        """scope (e.g. "project:laptop"): memories in that scope rank first (PLAN.md 7).
        time_range: AUTO reads it from the query; a DateRange is used as given; None turns it off."""
        rng = self.resolve_range(query, time_range, today)
        words = self.query_words(query, rng)
        if not words:
            return self._in_range(rng, k, include_sensitive) if rng else []
        ranked: dict[str, float] = {}

        word_rows = self.db.execute(
            """SELECT w.id FROM memory_words w JOIN memory_index i ON i.id = w.id
               WHERE memory_words MATCH ? AND i.status='active' ORDER BY bm25(memory_words) LIMIT 50""",
            (" OR ".join(_quote(w) for w in words),),
        ).fetchall()
        for rank, (mid,) in enumerate(word_rows):
            ranked[mid] = ranked.get(mid, 0.0) + 1.0 / (RRF_K + rank + 1)
        exact = {r[0] for r in word_rows}

        grams = set().union(*(_trigrams(w) for w in words if len(w) >= 3))
        if grams:
            tri_rows = self.db.execute(
                """SELECT t.id, t.text FROM memory_trigrams t JOIN memory_index i ON i.id = t.id
                   WHERE memory_trigrams MATCH ? AND i.status='active' ORDER BY bm25(memory_trigrams) LIMIT 50""",
                (" OR ".join(_quote(g) for g in sorted(grams)),),
            ).fetchall()
            rank = 0
            for mid, text in tri_rows:
                if mid not in exact and not self._fuzzy_match(words, text):
                    continue  # gate: a few shared trigrams is not a match
                ranked[mid] = ranked.get(mid, 0.0) + 1.0 / (RRF_K + rank + 1)
                rank += 1

        if rng and ranked:
            # Time-aware list: the matches saved inside the asked period, in their current order,
            # fused like the other lists (a boost, not a filter).
            marks = ",".join("?" * len(ranked))
            dates = dict(self.db.execute(f"SELECT id, valid_from FROM memory_index WHERE id IN ({marks})",
                                         list(ranked)).fetchall())
            in_range = [mid for mid in sorted(ranked, key=ranked.get, reverse=True)  # type: ignore[arg-type]
                        if rng.contains_iso(dates.get(mid) or "")]
            for rank, mid in enumerate(in_range):
                ranked[mid] += 1.0 / (RRF_K + rank + 1)

        hits: list[SearchHit] = []
        for mid, score in ranked.items():
            mem = self.get(mid)
            if not mem or (not include_sensitive and mem.sensitivity in ("sensitive", "secret")):
                continue
            boost = 1.5 if scope and mem.scope == scope else 1.0
            hits.append(SearchHit(mem, score * self._recency(mem) * boost))
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:k]

    def _in_range(self, rng: DateRange, k: int, include_sensitive: bool) -> list[SearchHit]:
        """A question that names only a time ("what did I tell you last week"): the active
        memories saved in that period, newest first."""
        rows = self.db.execute(
            "SELECT id, valid_from FROM memory_index WHERE status='active' ORDER BY valid_from DESC, id DESC").fetchall()
        hits: list[SearchHit] = []
        for mid, valid_from in rows:
            if not rng.contains_iso(valid_from or ""):
                continue
            mem = self.get(mid)
            if not mem or (not include_sensitive and mem.sensitivity in ("sensitive", "secret")):
                continue
            hits.append(SearchHit(mem, 1.0 / (RRF_K + len(hits) + 1)))
            if len(hits) >= k:
                break
        return hits

    @staticmethod
    def _fuzzy_match(words: list[str], text: str) -> bool:
        doc_grams = _trigrams(text)
        for w in words:
            g = _trigrams(w)
            if len(g) >= 2 and len(g & doc_grams) / len(g) >= MIN_TRIGRAM_COVERAGE:
                return True
        return False

    @staticmethod
    def _recency(mem: Memory) -> float:
        try:
            age = (date.today() - date.fromisoformat(mem.valid_from)).days
        except ValueError:
            return 1.0
        return 1.0 + 0.1 * math.exp(-max(age, 0) / 90)

    # ---- MEMORY.md ----

    def write_memory_md(self) -> Path:
        """Index of active memories, always in the prompt. Kept under 200 lines."""
        lines = ["# Memory index", ""]
        for t, folder in TYPE_DIRS.items():
            mems = self.list(type=t)
            if not mems:
                continue
            lines.append(f"## {folder}")
            for m in mems:
                if m.sensitivity in ("sensitive", "secret"):
                    lines.append(f"- {m.id}: (sensitive)")
                else:
                    lines.append(f"- {m.id}: {m.summary_en or m.name}")
            lines.append("")
        if len(lines) > MEMORY_INDEX_MAX_LINES:
            lines = lines[:MEMORY_INDEX_MAX_LINES - 1] + ["- ... (more memories; use memory_search)"]
        path = self.root / "MEMORY.md"
        path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        return path
