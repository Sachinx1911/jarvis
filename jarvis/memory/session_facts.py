"""Fact-augmented, cross-script, time-aware session search.

Past chats are searched through session_text (raw messages, written by db.py). This module
adds two indexes of its own (created with CREATE ... IF NOT EXISTS, no db.py migration):

- session_facts: when a session's memories are extracted, the extracted facts (name,
  subject, English summary, keywords, plus their romanized keys) are indexed here, pointing
  at the user message that holds the memory's evidence quote. A search for "brother's
  wedding" then finds the chat line "bhavacha lagna december madhe ahe", which shares no
  word with the question (LongMemEval "fact-augmented key expansion").
- session_keys: every chat line as canonical romanized keys (jarvis.memory.translit), so a
  Devanagari question finds a romanized chat line and the reverse. Filled lazily from
  session_text at search time.

search() fuses up to five ranked lists with reciprocal rank fusion:
1. raw message text (session_text),
2. script keys (session_keys),
3. extracted facts (session_facts), mapped to their evidence message,
4. time: candidates whose message time falls in the question's date range,
5. support: evidence messages of memories already retrieved for this turn.

Facts of sensitive memories are not indexed. Both tables are only indexes: reindex_all()
rebuilds session_facts from mem_extracted_sessions.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Iterable

from jarvis.memory.model import Memory
from jarvis.memory.timefilter import DateRange, extract_range
from jarvis.memory.translit import expand_words, index_variants, query_keys, text_keys

RRF_K = 60
SAVED_ACTIONS = ("ADD", "UPDATE", "SUPERSEDE")
INDEXED_SENSITIVITIES = ("public", "normal")
AUTO = "auto"
NARROW_DAYS = 2        # a range this short also lists all its messages as candidates
SUPERSEDED_FACTOR = 0.5   # score kept by a chat line whose memory was superseded

SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS session_facts USING fts5(
    session_id UNINDEXED, memory_id UNINDEXED, message_id UNINDEXED, ts UNINDEXED, text, tokenize='trigram'
);
CREATE VIRTUAL TABLE IF NOT EXISTS session_keys USING fts5(
    message_id UNINDEXED, text, tokenize='trigram'
);
CREATE TABLE IF NOT EXISTS session_keys_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    last_rowid INTEGER NOT NULL DEFAULT 0
);
"""


def ensure_table(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


# ---- session_keys ----

def sync_keys(conn: sqlite3.Connection) -> int:
    """Add romanized keys for chat lines stored since the last search. Returns how many."""
    ensure_table(conn)
    row = conn.execute("SELECT last_rowid FROM session_keys_state WHERE id=1").fetchone()
    last = int(row[0]) if row else 0
    rows = conn.execute("SELECT rowid, message_id, text FROM session_text WHERE rowid > ? ORDER BY rowid",
                        (last,)).fetchall()
    if not rows:
        return 0
    conn.executemany("INSERT INTO session_keys (message_id, text) VALUES (?, ?)",
                     [(mid, text_keys(text or "")) for _, mid, text in rows])
    conn.execute("INSERT INTO session_keys_state (id, last_rowid) VALUES (1, ?) "
                 "ON CONFLICT(id) DO UPDATE SET last_rowid=excluded.last_rowid", (rows[-1][0],))
    conn.commit()
    return len(rows)


# ---- session_facts ----

def _load_memory(conn: sqlite3.Connection, memory_id: str) -> Memory | None:
    row = conn.execute("SELECT path FROM memory_index WHERE id=?", (memory_id,)).fetchone()
    if not row:
        return None
    try:
        return Memory.from_markdown(Path(row[0]).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _evidence_message(conn: sqlite3.Connection, session_id: str, evidence: str) -> tuple[int, str] | None:
    """The user message of this session that holds the memory's evidence quote (else its last user message)."""
    rows = conn.execute(
        "SELECT message_id, ts, text FROM session_text WHERE session_id=? AND role='user' ORDER BY message_id",
        (session_id,)).fetchall()
    if not rows:
        return None
    quotes = [_norm(q) for q in evidence.split(" | ") if q.strip()]
    for mid, ts, text in rows:
        low = _norm(text)
        if any(q and q in low for q in quotes):
            return int(mid), ts
    mid, ts, _ = rows[-1]
    return int(mid), ts


def index_session(conn: sqlite3.Connection, session_id: str, results: Iterable) -> int:
    """Index the facts saved from one session. `results` are the extractor's (action, memory id)
    pairs. Returns the number of facts indexed."""
    ensure_table(conn)
    count = 0
    for item in results or []:
        try:
            action, memory_id = item[0], item[1]
        except (TypeError, IndexError):
            continue
        if action not in SAVED_ACTIONS:
            continue
        mem = _load_memory(conn, str(memory_id))
        if mem is None or mem.sensitivity not in INDEXED_SENSITIVITIES:
            continue
        where = _evidence_message(conn, session_id, mem.evidence)
        if where is None:
            continue
        message_id, ts = where
        text = " ".join(x for x in (mem.name, mem.subject, mem.summary_en, mem.keywords) if x).lower()
        extra = index_variants(text)
        conn.execute("DELETE FROM session_facts WHERE session_id=? AND memory_id=?", (session_id, mem.id))
        conn.execute("INSERT INTO session_facts (session_id, memory_id, message_id, ts, text) VALUES (?, ?, ?, ?, ?)",
                     (session_id, mem.id, message_id, ts, f"{text}\n{extra}".strip()))
        count += 1
    conn.commit()
    return count


def reindex_all(conn: sqlite3.Connection) -> int:
    """Rebuild session_facts from the extraction records (after `jarvis memory reindex` or an upgrade)."""
    ensure_table(conn)
    conn.execute("DELETE FROM session_facts")
    try:
        rows = conn.execute("SELECT session_id, results_json FROM mem_extracted_sessions").fetchall()
    except sqlite3.OperationalError:
        conn.commit()
        return 0
    total = 0
    for sid, results_json in rows:
        try:
            results = json.loads(results_json or "[]")
        except ValueError:
            continue
        total += index_session(conn, sid, results)
    conn.commit()
    return total


# ---- search ----

@dataclass
class SessionHit:
    message_id: int
    session_id: str
    role: str
    ts: str
    text: str
    score: float = 0.0
    via: set[str] = field(default_factory=set)       # text | keys | fact | time | support
    memory_ids: list[str] = field(default_factory=list)
    superseded: list[str] = field(default_factory=list)  # memories from this line that were later replaced


def _match_expr(words: list[str]) -> str:
    return " OR ".join('"' + w.replace('"', '""') + '"' for w in words)


def search(conn: sqlite3.Connection, query: str, limit: int = 5, exclude_session: str | None = None,
           time_range: DateRange | str | None = AUTO, today: date | None = None, use_facts: bool = True,
           script_forms: bool = True, time_aware: bool = True,
           support_memory_ids: Iterable[str] = ()) -> list[SessionHit]:
    """Past chat messages for a question, best first (see the module docstring)."""
    from jarvis.memory.store import STOPWORDS, _words

    ensure_table(conn)
    rng: DateRange | None
    if not time_aware:
        rng = None
    elif time_range == AUTO:
        rng = extract_range(query, today or date.today())
    else:
        rng = time_range  # type: ignore[assignment]
    base = _words(query)
    if rng is not None:
        base = [w for w in base if w not in rng.words]
    words = expand_words(base, STOPWORDS) if script_forms else base
    words = [w for w in words if len(w) >= 3]   # the trigram index cannot match shorter words
    keys = query_keys(base) if script_forms else []
    keys = [k for k in keys if k not in STOPWORDS]
    if keys:
        sync_keys(conn)

    hits: dict[int, SessionHit] = {}
    scores: dict[int, float] = {}

    def add(rank: int, mid: int, via: str, memory_id: str | None = None) -> None:
        scores[mid] = scores.get(mid, 0.0) + 1.0 / (RRF_K + rank + 1)
        hit = hits.get(mid)
        if hit is not None:
            hit.via.add(via)
            if memory_id and memory_id not in hit.memory_ids:
                hit.memory_ids.append(memory_id)

    def load(mids: list[int]) -> None:
        missing = list(dict.fromkeys(m for m in mids if m not in hits))
        if not missing:
            return
        marks = ",".join("?" * len(missing))
        for mid, sid, role, ts, text in conn.execute(
                f"SELECT message_id, session_id, role, ts, text FROM session_text WHERE message_id IN ({marks})",
                missing):
            hits[int(mid)] = SessionHit(int(mid), sid, role, ts, text)

    def ranked_list(sql: str, expr: str, via: str) -> None:
        rows = conn.execute(sql, (expr,)).fetchall()
        load([int(r[0]) for r in rows])
        seen: set[int] = set()
        rank = 0
        for row in rows:
            mid = int(row[0])
            memory_id = row[1] if len(row) > 1 else None
            if mid in seen:
                if memory_id and mid in hits and memory_id not in hits[mid].memory_ids:
                    hits[mid].memory_ids.append(memory_id)
                continue
            seen.add(mid)
            add(rank, mid, via, memory_id)
            rank += 1

    if words:
        ranked_list("""SELECT message_id FROM session_text WHERE session_text MATCH ?
                       ORDER BY bm25(session_text) LIMIT 50""", _match_expr(words), "text")
    if keys:
        ranked_list("""SELECT message_id FROM session_keys WHERE session_keys MATCH ?
                       ORDER BY bm25(session_keys) LIMIT 50""", _match_expr(keys), "keys")
    if use_facts and (words or keys):
        ranked_list("""SELECT message_id, memory_id FROM session_facts WHERE session_facts MATCH ?
                       ORDER BY bm25(session_facts) LIMIT 50""", _match_expr(list(dict.fromkeys(words + keys))),
                    "fact")
    narrow = rng is not None and (rng.end - rng.start).days <= NARROW_DAYS
    if rng is not None and (narrow or not (words or keys)):
        # Only a time was asked ("what did we talk about yesterday"), or a day or two: the
        # messages from then are candidates too, user lines first. Words in another language
        # ("gym" vs "जिम") still find yesterday's chat this way.
        lo, hi = rng.utc_bounds()
        rows = conn.execute(
            """SELECT message_id FROM session_text WHERE ts >= ? AND ts <= ?
               ORDER BY CASE role WHEN 'user' THEN 0 ELSE 1 END, ts DESC LIMIT 50""", (lo, hi)).fetchall()
        load([int(r[0]) for r in rows])
        for rank, (mid,) in enumerate(rows):
            add(rank, int(mid), "time")

    support = [m for m in dict.fromkeys(support_memory_ids) if m] if use_facts else []
    if support:
        marks = ",".join("?" * len(support))
        srows = conn.execute(
            f"SELECT message_id, memory_id FROM session_facts WHERE memory_id IN ({marks})", support).fetchall()
        order = {m: i for i, m in enumerate(support)}
        srows.sort(key=lambda r: order.get(r[1], len(order)))
        load([int(r[0]) for r in srows])
        for rank, (mid, memory_id) in enumerate(srows):
            add(rank, int(mid), "support", memory_id)

    if rng is not None and (words or keys):
        in_range = [mid for mid in sorted(scores, key=scores.__getitem__, reverse=True)
                    if mid in hits and rng.contains_utc_ts(hits[mid].ts)]
        for rank, mid in enumerate(in_range):
            add(rank, mid, "time")

    if use_facts and scores:
        _mark_superseded(conn, hits, scores)

    out = []
    for mid, score in sorted(scores.items(), key=lambda kv: kv[1], reverse=True):
        hit = hits.get(mid)
        if hit is None or (exclude_session and hit.session_id == exclude_session):
            continue
        hit.score = score
        out.append(hit)
        if len(out) >= limit:
            break
    return out


def _mark_superseded(conn: sqlite3.Connection, hits: dict[int, SessionHit], scores: dict[int, float]) -> None:
    """A chat line that is the evidence of a memory later superseded holds an outdated answer
    ("office is in Hinjewadi"): it is ranked lower and labelled, never hidden."""
    mids = [m for m in scores if m in hits]
    marks = ",".join("?" * len(mids))
    rows = conn.execute(
        f"""SELECT f.message_id, f.memory_id FROM session_facts f JOIN memory_index i ON i.id = f.memory_id
            WHERE f.message_id IN ({marks}) AND i.status = 'superseded'""", mids).fetchall()
    for message_id, memory_id in rows:
        hit = hits.get(int(message_id))
        if hit is None or memory_id in hit.superseded:
            continue
        hit.superseded.append(memory_id)
        scores[hit.message_id] *= SUPERSEDED_FACTOR


def latest_session(conn: sqlite3.Connection, user_text: str) -> str | None:
    """The session whose newest stored message is this exact user text: the chat in progress
    (ChatSession.send stores the user message before the context is built)."""
    row = conn.execute("SELECT session_id, text FROM session_text ORDER BY rowid DESC LIMIT 1").fetchone()
    if row and _norm(row[1] or "") == _norm(user_text):
        return row[0]
    return None
