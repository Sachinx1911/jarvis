"""Read models for the trust features: where a memory came from, what was in a reply's
context ("Why did Jarvis say that?"), the memory trash, and standing approvals.

Nothing here calls a model. Sensitive memories stay masked unless revealed (audited by the
caller); chat lines are P3-redacted before they leave this module.
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from jarvis.memory.model import Memory
from jarvis.privacy import redact_p3
from jarvis.web.data import SENSITIVE, memory_json

MAX_AUDIT_BYTES = 8 * 1024 * 1024   # how much of the audit log the "how saved" lookup reads
EXCERPT_CHARS = 300
MAX_SOURCE_SESSIONS = 5


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lower()


def _clip(text: str, n: int = EXCERPT_CHARS) -> str:
    text = redact_p3(text or "")[0]
    return text if len(text) <= n else text[:n] + " ..."


# ---- turn context log ("Why did Jarvis say that?") ----

TURN_SCHEMA = """
CREATE TABLE IF NOT EXISTS turn_context (
    id INTEGER PRIMARY KEY,
    session_id TEXT NOT NULL,
    ts TEXT NOT NULL DEFAULT (datetime('now')),
    user_message_id INTEGER,
    reply_message_id INTEGER,
    memory_ids TEXT NOT NULL,
    excerpt_ids TEXT NOT NULL,
    withheld INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS turn_context_session ON turn_context(session_id);
"""


def ensure_turn_table(conn: sqlite3.Connection) -> None:
    conn.executescript(TURN_SCHEMA)


def record_turn(conn: sqlite3.Connection, session_id: str, built) -> int:
    """Store which memories and past-chat excerpts were in the context of the latest reply of
    this session (`built` is the turn's core.context.BuiltContext). Returns the turn id."""
    ensure_turn_table(conn)

    def last(role: str) -> int | None:
        row = conn.execute("SELECT MAX(id) FROM messages WHERE session_id=? AND role=?", (session_id, role)).fetchone()
        return row[0] if row else None

    cur = conn.execute(
        """INSERT INTO turn_context (session_id, user_message_id, reply_message_id, memory_ids, excerpt_ids, withheld)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (session_id, last("user"), last("assistant"), json.dumps(list(getattr(built, "memory_ids", []) or [])),
         json.dumps([int(x) for x in getattr(built, "excerpt_ids", []) or []]), int(getattr(built, "withheld", 0) or 0)))
    conn.commit()
    return int(cur.lastrowid)


class TurnRecorder:
    """Wraps a ChatSession's context builder to catch each turn's BuiltContext, then records it.
    Sessions without a context builder (tests' fakes) record nothing."""

    def __init__(self, session):
        self.session = session
        self.built = None
        builder = getattr(session, "context", None)
        self.active = builder is not None and callable(getattr(builder, "build", None))
        if self.active:
            original = builder.build

            def build(*args, **kwargs):
                self.built = original(*args, **kwargs)
                return self.built

            builder.build = build

    def record(self, conn: sqlite3.Connection) -> int | None:
        built, self.built = self.built, None
        if not self.active or built is None:
            return None
        return record_turn(conn, self.session.session_id, built)


def _line(conn: sqlite3.Connection, message_id: int) -> dict | None:
    """One chat line (user or Jarvis text) from the session-search table."""
    row = conn.execute("SELECT message_id, session_id, ts, role, text FROM session_text WHERE message_id=?",
                       (message_id,)).fetchone()
    if not row:
        return None
    return {"message_id": int(row[0]), "session_id": row[1], "ts": row[2], "role": row[3], "text": _clip(row[4])}


def turn_view(rt, turn_id: int) -> dict[str, Any] | None:
    conn = rt.store.conn
    ensure_turn_table(conn)
    row = conn.execute("SELECT id, session_id, ts, memory_ids, excerpt_ids, withheld FROM turn_context WHERE id=?",
                       (turn_id,)).fetchone()
    if not row:
        return None
    memories = []
    for mid in json.loads(row[3]):
        m = rt.memory.get(mid)
        if m is None:
            memories.append({"id": mid, "name": "(deleted)", "summary_en": "", "type": "", "sensitivity": "",
                             "masked": False, "status": "deleted"})
            continue
        d = memory_json(m)
        memories.append({k: d[k] for k in ("id", "name", "summary_en", "type", "sensitivity", "masked", "status")})
    excerpts = [x for x in (_line(conn, int(i)) for i in json.loads(row[4])) if x]
    return {"turn_id": row[0], "session_id": row[1], "ts": row[2], "memories": memories, "excerpts": excerpts,
            "withheld": row[5]}


# ---- where a memory came from ----

def _interview_questions() -> list[str]:
    from jarvis.paths import PROMPTS_DIR

    try:
        text = (PROMPTS_DIR / "interview.md").read_text(encoding="utf-8")
    except OSError:
        return []
    return [l[2:].strip() for l in text.splitlines() if l.startswith("- ")]


def _audit_events(audit_path: Path, memory_id: str) -> list[dict]:
    """memory_saved / interview_answer events that name this memory (recent part of the log)."""
    if not audit_path.exists():
        return []
    with audit_path.open("rb") as f:
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(0, size - MAX_AUDIT_BYTES))
        lines = f.read().decode("utf-8", errors="replace").splitlines()
    out = []
    needle = f'"{memory_id}"'
    for line in lines:
        if needle not in line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("event") == "memory_saved" and rec.get("id") == memory_id:
            out.append(rec)
        elif rec.get("event") == "interview_answer" and rec.get("memory_id") == memory_id:
            out.append(rec)
    return out


def save_method(m: Memory, events: list[dict]) -> tuple[str, str | None]:
    """(remember | extract | interview | import | unknown, when it was saved)."""
    saved_at = next((e.get("ts") for e in events if e.get("event") == "memory_saved"), None)
    if m.source == "imported":
        return "import", saved_at
    if any(e.get("event") == "interview_answer" for e in events):
        return "interview", saved_at
    if any(_norm(m.evidence).startswith(_norm(q)) for q in _interview_questions()):
        return "interview", saved_at
    hows = [str(e.get("how", "")) for e in events if e.get("event") == "memory_saved"]
    if any(h.startswith("extract") for h in hows):
        return "extract", saved_at
    if "remember" in hows:
        return "remember", saved_at
    return "unknown", saved_at or m.valid_from


def source_sessions(conn: sqlite3.Connection, m: Memory) -> list[dict]:
    """Chat lines the memory came from: the session-facts index first, then the user lines
    that hold its evidence quote (session search)."""
    found: dict[int, dict] = {}
    try:
        rows = conn.execute("SELECT session_id, message_id, ts FROM session_facts WHERE memory_id=?", (m.id,)).fetchall()
    except sqlite3.OperationalError:
        rows = []
    for sid, mid, ts in rows:
        found[int(mid)] = {"session_id": sid, "message_id": int(mid), "ts": ts, "role": "user"}
    quotes = [_norm(q) for q in (m.evidence or "").split(" | ") if len(_norm(q)) >= 8]
    if quotes and len(found) < MAX_SOURCE_SESSIONS:
        try:
            lines = conn.execute(
                "SELECT message_id, session_id, ts, text FROM session_text WHERE role='user' ORDER BY message_id DESC"
            ).fetchall()
        except sqlite3.OperationalError:
            lines = []
        for mid, sid, ts, text in lines:
            low = _norm(text)
            if any(q in low for q in quotes):
                found.setdefault(int(mid), {"session_id": sid, "message_id": int(mid), "ts": ts, "role": "user"})
            if len(found) >= MAX_SOURCE_SESSIONS:
                break
    out = []
    for mid in sorted(found):
        item = found[mid]
        line = _line(conn, mid)
        item["excerpt"] = line["text"] if line else ""
        out.append(item)
    return out


def supersede_chain(rt, m: Memory) -> list[dict]:
    """Older versions: memories whose superseded_by points (step by step) at this one."""
    older = {x.superseded_by: x for x in rt.memory.list(status="superseded") if x.superseded_by}
    chain, seen, cur = [], {m.id}, m.id
    while cur in older and older[cur].id not in seen:
        prev = older[cur]
        seen.add(prev.id)
        d = memory_json(prev)
        chain.append({k: d[k] for k in ("id", "name", "summary_en", "status", "valid_from", "valid_until",
                                        "superseded_by")})
        cur = prev.id
    return chain


def memory_source(rt, m: Memory, reveal: bool = False) -> dict[str, Any]:
    masked = m.sensitivity in SENSITIVE and not reveal
    method, saved_at = save_method(m, _audit_events(rt.audit.path, m.id))
    sessions = source_sessions(rt.store.conn, m)
    if masked:
        for s in sessions:
            s["excerpt"] = ""
    return {"id": m.id, "masked": masked, "evidence": "" if masked else m.evidence, "method": method,
            "saved_at": saved_at, "last_used": m.last_used, "use_count": m.use_count, "sessions": sessions,
            "chain": supersede_chain(rt, m), "newer": m.superseded_by or None}


def session_lines(rt, session_id: str, around: int | None, n: int = 6) -> list[dict]:
    """Lines of a past chat (user and Jarvis text only), around one message when given.
    Lines that quote a sensitive memory's evidence are masked."""
    conn = rt.store.conn
    n = max(1, min(int(n), 30))
    if around is not None:
        rows = conn.execute(
            """SELECT * FROM (SELECT message_id, ts, role, text FROM session_text WHERE session_id=? AND message_id<=?
                              ORDER BY message_id DESC LIMIT ?)
               UNION SELECT * FROM (SELECT message_id, ts, role, text FROM session_text WHERE session_id=?
                              AND message_id>? ORDER BY message_id LIMIT ?) ORDER BY 1""",
            (session_id, around, n + 1, session_id, around, n)).fetchall()
    else:
        rows = conn.execute("SELECT message_id, ts, role, text FROM session_text WHERE session_id=? ORDER BY message_id "
                            "LIMIT ?", (session_id, n * 4)).fetchall()
    secret_quotes = [_norm(q) for m in rt.memory.list(status=None) if m.sensitivity in SENSITIVE
                     for q in (m.evidence or "").split(" | ") if len(_norm(q)) >= 8]
    out = []
    for mid, ts, role, text in rows:
        hidden = any(q in _norm(text) for q in secret_quotes)
        out.append({"id": mid, "ts": ts, "role": role,
                    "text": "(sensitive: hidden)" if hidden else _clip(text, 1200), "masked": hidden})
    return out


# ---- trash ----

def trash_json(rt) -> list[dict]:
    out = []
    for file, m in rt.memory.trashed():
        masked = m.sensitivity in SENSITIVE
        stamp = Path(file).stem.rsplit(".", 1)[-1]
        out.append({"file": file, "id": m.id, "name": "(sensitive)" if masked else m.name, "type": m.type,
                    "sensitivity": m.sensitivity, "masked": masked,
                    "trashed_at": f"{stamp[0:4]}-{stamp[4:6]}-{stamp[6:8]} {stamp[9:11]}:{stamp[11:13]}"
                    if len(stamp) >= 13 else ""})
    return out


# ---- standing approvals ----

def grant_tools(rt) -> list[dict]:
    """Tools a standing approval may cover (T1/T2 only)."""
    from jarvis.control.grants import GRANTABLE_TIERS
    from jarvis.web.data import tools_json

    return [{"name": t["name"], "tier": t["tier"]} for t in tools_json(rt)["tools"]
            if t["tier"] in GRANTABLE_TIERS and t["enabled"]]


def grant_store(rt):
    from jarvis.control.grants import GrantStore
    from jarvis.tools.catalog import file_roots

    return GrantStore(rt.store.conn, file_roots(rt.paths.home, rt.config.tools))
