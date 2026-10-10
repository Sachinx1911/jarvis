"""SQLite store owned by Jarvis (PLAN.md 5.7). Messages are kept in neutral form."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from pathlib import Path

from jarvis.providers.base import LLMResponse, Message, TextPart, ToolCall, ToolResult

SCHEMA_VERSION = 3

_SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    state TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS task_events (
    id INTEGER PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(id),
    ts TEXT NOT NULL DEFAULT (datetime('now')),
    kind TEXT NOT NULL,
    detail TEXT
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY,
    session_id TEXT NOT NULL,
    ts TEXT NOT NULL DEFAULT (datetime('now')),
    role TEXT NOT NULL,
    parts TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS messages_session ON messages(session_id);
CREATE TABLE IF NOT EXISTS tool_runs (
    id INTEGER PRIMARY KEY,
    task_id TEXT,
    ts TEXT NOT NULL DEFAULT (datetime('now')),
    tool TEXT NOT NULL,
    tier TEXT NOT NULL,
    arguments TEXT,
    result TEXT,
    ok INTEGER
);
CREATE TABLE IF NOT EXISTS approvals (
    id INTEGER PRIMARY KEY,
    task_id TEXT,
    ts TEXT NOT NULL DEFAULT (datetime('now')),
    action TEXT NOT NULL,
    decision TEXT
);
CREATE TABLE IF NOT EXISTS model_usage (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL DEFAULT (datetime('now')),
    session_id TEXT,
    task_id TEXT,
    route TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    input_tokens INTEGER,
    output_tokens INTEGER,
    cached_tokens INTEGER,
    cost_usd REAL,
    latency_ms INTEGER,
    stop_reason TEXT,
    fallback INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS adapter_state (
    message_id INTEGER PRIMARY KEY REFERENCES messages(id),
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    state TEXT NOT NULL
);
"""

# v2: memory index (files in memory/ are the source of truth) and session search.
_SCHEMA_V2 = """
CREATE TABLE IF NOT EXISTS memory_index (
    id TEXT PRIMARY KEY,
    path TEXT NOT NULL,
    type TEXT NOT NULL,
    status TEXT NOT NULL,
    name TEXT NOT NULL,
    subject TEXT,
    scope TEXT,
    sensitivity TEXT NOT NULL,
    valid_from TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE VIRTUAL TABLE IF NOT EXISTS memory_words USING fts5(id UNINDEXED, text, tokenize='unicode61');
CREATE VIRTUAL TABLE IF NOT EXISTS memory_trigrams USING fts5(id UNINDEXED, text, tokenize='trigram');
CREATE VIRTUAL TABLE IF NOT EXISTS session_text USING fts5(
    message_id UNINDEXED, session_id UNINDEXED, role UNINDEXED, ts UNINDEXED, text, tokenize='trigram'
);
"""

# v3: task system (PLAN.md section 10) and notional cost for subscription calls.
_SCHEMA_V3 = """
ALTER TABLE tasks ADD COLUMN goal TEXT NOT NULL DEFAULT '';
ALTER TABLE tasks ADD COLUMN project TEXT;
ALTER TABLE tasks ADD COLUMN priority INTEGER NOT NULL DEFAULT 2;
ALTER TABLE tasks ADD COLUMN deadline TEXT;
ALTER TABLE tasks ADD COLUMN owner TEXT NOT NULL DEFAULT 'jarvis';
ALTER TABLE tasks ADD COLUMN budget TEXT;
ALTER TABLE tasks ADD COLUMN plan TEXT;
ALTER TABLE tasks ADD COLUMN checkpoint TEXT;
ALTER TABLE tasks ADD COLUMN last_error TEXT;
ALTER TABLE tasks ADD COLUMN retries INTEGER NOT NULL DEFAULT 0;
ALTER TABLE tasks ADD COLUMN current_step TEXT;
ALTER TABLE model_usage ADD COLUMN notional_usd REAL;
ALTER TABLE tool_runs ADD COLUMN agent TEXT;
CREATE INDEX IF NOT EXISTS task_events_task ON task_events(task_id);
CREATE INDEX IF NOT EXISTS model_usage_task ON model_usage(task_id);
CREATE INDEX IF NOT EXISTS tool_runs_task ON tool_runs(task_id);
"""

_MIGRATIONS = {1: _SCHEMA_V1, 2: _SCHEMA_V2, 3: _SCHEMA_V3}


def notional_usd(resp: LLMResponse) -> float | None:
    """What the call would cost at API prices: real cost if billed, else the CLI's estimate."""
    if resp.cost_usd is not None:
        return resp.cost_usd
    value = (resp.adapter_state or {}).get("notional_usd")
    return float(value) if isinstance(value, (int, float)) else None


def _part_to_json(part: TextPart | ToolCall | ToolResult) -> dict:
    return {"type": type(part).__name__, **asdict(part)}


def _statements(script: str) -> list[str]:
    out, buf = [], ""
    for line in script.splitlines(keepends=True):
        buf += line
        if sqlite3.complete_statement(buf):
            out.append(buf.strip())
            buf = ""
    return [s for s in out if s]


class Store:
    def __init__(self, path: Path):
        # timeout: wait for another writer (e.g. a migration in another thread) instead of failing
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, timeout=30)
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.migrate()

    def migrate(self) -> None:
        """Each step runs in one write-locked transaction: two processes or threads opening the
        database at once cannot both apply it, and a crash mid-step leaves nothing half-done."""
        if self.conn.execute("PRAGMA user_version").fetchone()[0] >= SCHEMA_VERSION:
            return
        self.conn.isolation_level = None  # manage the transaction ourselves
        try:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                version = self.conn.execute("PRAGMA user_version").fetchone()[0]  # re-read under the lock
                for target in range(version + 1, SCHEMA_VERSION + 1):
                    for statement in _statements(_MIGRATIONS[target]):
                        self.conn.execute(statement)
                    self.conn.execute(f"PRAGMA user_version = {target}")
                self.conn.execute("COMMIT")
            except BaseException:
                self.conn.execute("ROLLBACK")
                raise
        finally:
            self.conn.isolation_level = ""

    def tables(self) -> set[str]:
        rows = self.conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'view')")
        return {r[0] for r in rows}

    def add_message(self, session_id: str, msg: Message) -> int:
        cur = self.conn.execute(
            "INSERT INTO messages (session_id, role, parts) VALUES (?, ?, ?)",
            (session_id, msg.role, json.dumps([_part_to_json(p) for p in msg.parts], ensure_ascii=False)),
        )
        message_id = cur.lastrowid
        text = msg.text_content()
        if text and msg.role in ("user", "assistant"):
            self.conn.execute(
                "INSERT INTO session_text (message_id, session_id, role, ts, text) VALUES (?, ?, ?, datetime('now'), ?)",
                (message_id, session_id, msg.role, text),
            )
        state = msg.adapter_state
        if state and "provider" in state and "model" in state:
            self.conn.execute(
                "INSERT INTO adapter_state (message_id, provider, model, state) VALUES (?, ?, ?, ?)",
                (message_id, state["provider"], state["model"], json.dumps(state, ensure_ascii=False)),
            )
        self.conn.commit()
        return message_id

    def record_usage(self, session_id: str | None, route: str, resp: LLMResponse, task_id: str | None = None) -> None:
        self.conn.execute(
            """INSERT INTO model_usage (session_id, task_id, route, provider, model, input_tokens,
               output_tokens, cached_tokens, cost_usd, latency_ms, stop_reason, notional_usd)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                session_id, task_id, route, resp.provider, resp.model,
                resp.usage.input_tokens, resp.usage.output_tokens, resp.usage.cached_tokens,
                resp.cost_usd, resp.latency_ms, resp.stop_reason, notional_usd(resp),
            ),
        )
        self.conn.commit()

    def search_sessions(self, query: str, limit: int = 5, exclude_session: str | None = None) -> list[dict]:
        """Past conversation lines matching any 3+ character word of the query."""
        words = [w for w in query.split() if len(w) >= 3]
        if not words:
            return []
        match = " OR ".join('"' + w.replace('"', '""') + '"' for w in words)
        rows = self.conn.execute(
            """SELECT session_id, role, ts, text FROM session_text WHERE session_text MATCH ?
               ORDER BY bm25(session_text) LIMIT ?""",
            (match, limit + 20),
        ).fetchall()
        out = [dict(zip(("session_id", "role", "ts", "text"), r)) for r in rows if r[0] != exclude_session]
        return out[:limit]

    def close(self) -> None:
        self.conn.close()
