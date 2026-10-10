"""Every chat turn records which memories and past-chat lines were in its context, so
"Why did Jarvis say that?" works for CLI and Telegram chats too, not only the dashboard.
Offline: fake provider, synthetic data only."""

import json
import logging
import sqlite3
from datetime import datetime
from types import SimpleNamespace

import pytest

from jarvis.config import load_config
from jarvis.control.audit import AuditLog
from jarvis.core.chat import ChatSession
from jarvis.core.runtime import make_chat, open_runtime
from jarvis.db import Store
from jarvis.memory.model import Memory
from jarvis.memory.store import MemoryStore
from jarvis.providers.fake import FakeProvider
from jarvis.routing.policy import RouteDecision
from jarvis.skills.loader import SkillLibrary

DECISION = RouteDecision("main_chat", "fake", "fake-1", "medium", "test")


@pytest.fixture
def env(tmp_path):
    store = Store(tmp_path / "data" / "jarvis.db")
    mem = MemoryStore(tmp_path, store)
    yield tmp_path, store, mem
    store.close()


def _session(env, script) -> ChatSession:
    home, store, mem = env
    return ChatSession(load_config(), FakeProvider(script=script), DECISION, store,
                       AuditLog(home / "data" / "audit.jsonl"), now=lambda: datetime(2026, 10, 10, 19, 30),
                       home=home, memory=mem, skills=SkillLibrary(home / "skills"))


def _turns(conn) -> list[tuple]:
    try:
        return conn.execute("SELECT id, session_id, reply_message_id, memory_ids FROM turn_context ORDER BY id").fetchall()
    except sqlite3.OperationalError:  # no table yet: nothing was recorded
        return []


def test_cli_session_records_every_turn(env):
    from jarvis.web.trust import turn_view

    _, store, mem = env
    m = mem.save(Memory(name="garden shed key", keywords="garden shed key drawer",
                        summary_en="The shed key is in the drawer.", evidence="the shed key is in the drawer"))
    s = _session(env, ["It is in the drawer, sir.", "You are welcome, sir."])
    assert s.send("where is the garden shed key?") == "It is in the drawer, sir."
    rows = _turns(store.conn)
    assert len(rows) == 1 and rows[0][0] == s.last_turn_id
    assert rows[0][1] == s.session_id and m.id in json.loads(rows[0][3])
    role = store.conn.execute("SELECT role FROM messages WHERE id=?", (rows[0][2],)).fetchone()[0]
    assert role == "assistant"  # the record points at Jarvis's reply
    why = turn_view(SimpleNamespace(store=store, memory=mem), s.last_turn_id)
    assert m.id in [x["id"] for x in why["memories"]]

    s.send("thanks")
    rows = _turns(store.conn)
    assert len(rows) == 2 and rows[1][0] == s.last_turn_id


def test_runtime_chat_records_turn(isolated):
    """CLI and Telegram build their sessions with core.runtime.make_chat."""
    rt = open_runtime()
    try:
        s = make_chat(rt, "fake")
        s.provider = s.loop.provider = FakeProvider(script=["Hello, sir."])
        assert s.send("hello") == "Hello, sir."
        assert s.last_turn_id and [r[0] for r in _turns(rt.store.conn)] == [s.last_turn_id]
    finally:
        rt.close()


def test_turn_recorder_wrapper_records_once(env):
    """The dashboard wraps context.build with its TurnRecorder and records the turn itself."""
    from jarvis.web.trust import TurnRecorder

    _, store, _ = env
    s = _session(env, ["ok"])
    recorder = TurnRecorder(s)
    s.send("hi")
    assert s.last_turn_id is None and _turns(store.conn) == []
    turn_id = recorder.record(store.conn)
    assert [r[0] for r in _turns(store.conn)] == [turn_id]


def test_dashboard_chat_records_each_turn_exactly_once(isolated):
    pytest.importorskip("fastapi")
    from tests.test_web_api import H, Scripted, _client

    with _client(factory=Scripted(["First reply, sir.", "Second reply, sir."])) as c:
        sid = c.post("/api/chat/sessions", headers=H).json()["id"]
        r1 = c.post(f"/api/chat/sessions/{sid}/messages", headers=H, json={"text": "first question"}).json()
        r2 = c.post(f"/api/chat/sessions/{sid}/messages", headers=H, json={"text": "second question"}).json()
    assert r1["turn_id"] and r2["turn_id"]
    rt = open_runtime()
    try:
        assert [r[0] for r in _turns(rt.store.conn)] == [r1["turn_id"], r2["turn_id"]]
    finally:
        rt.close()


def test_recording_failure_does_not_break_send(env, monkeypatch, caplog):
    import jarvis.web.trust as trust

    def broken(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(trust, "record_turn", broken)
    home, store, _ = env
    s = _session(env, ["Still here, sir.", "Again, sir."])
    with caplog.at_level(logging.WARNING, logger="jarvis.core.chat"):
        assert s.send("hello") == "Still here, sir."
    assert s.last_turn_id is None and "database is locked" in caplog.text
    events = [json.loads(line) for line in (home / "data" / "audit.jsonl").read_text(encoding="utf-8").splitlines()]
    errors = [e for e in events if e["event"] == "turn_record_error"]
    assert errors and errors[0]["session_id"] == s.session_id and "OperationalError" in errors[0]["error"]
    assert s.history[-1].role == "assistant"

    # Even failing to log the error does not break the turn.
    real_write = s.audit.write

    def flaky_write(event, **fields):
        if event == "turn_record_error":
            raise OSError("disk full")
        real_write(event, **fields)

    monkeypatch.setattr(s.audit, "write", flaky_write)
    assert s.send("again") == "Again, sir."
