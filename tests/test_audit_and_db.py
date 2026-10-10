import json

from jarvis.control.audit import REDACTED, AuditLog
from jarvis.db import SCHEMA_VERSION, Store
from jarvis.providers.base import Message, ToolCall


def test_audit_redacts_secrets(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    log.write("x", api_key="abc", access_token="t", input_tokens=12, nested={"Authorization": "Bearer z"},
              note="key sk-ant-abc123 leaked")
    record = json.loads((tmp_path / "audit.jsonl").read_text(encoding="utf-8"))
    assert record["api_key"] == REDACTED and record["access_token"] == REDACTED
    assert record["input_tokens"] == 12
    assert record["nested"]["Authorization"] == REDACTED
    assert "sk-ant" not in record["note"]


def test_audit_is_append_only(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    log.write("a")
    log.write("b")
    lines = (tmp_path / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(l)["event"] for l in lines] == ["a", "b"]


def test_schema_created_once(tmp_path):
    store = Store(tmp_path / "j.db")
    assert {"tasks", "task_events", "messages", "tool_runs", "approvals", "model_usage", "adapter_state"} <= store.tables()
    assert store.conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    store.close()
    Store(tmp_path / "j.db").close()  # reopening is a no-op


def test_messages_stored_neutral_with_adapter_state(tmp_path):
    store = Store(tmp_path / "j.db")
    msg = Message("assistant", [ToolCall("t1", "read_file", {"path": "a.txt"})],
                  adapter_state={"provider": "anthropic", "model": "m", "content": []})
    mid = store.add_message("s1", msg)
    parts = json.loads(store.conn.execute("SELECT parts FROM messages WHERE id=?", (mid,)).fetchone()[0])
    assert parts == [{"type": "ToolCall", "id": "t1", "name": "read_file", "arguments": {"path": "a.txt"}}]
    assert store.conn.execute("SELECT provider FROM adapter_state WHERE message_id=?", (mid,)).fetchone() == ("anthropic",)


def test_concurrent_first_open_migrates_once(tmp_path):
    """Several threads opening an old database at once (the dashboard does this) must not fail."""
    import sqlite3
    import threading

    path = tmp_path / "j.db"
    old = sqlite3.connect(path)
    from jarvis.db import _SCHEMA_V1
    old.executescript(_SCHEMA_V1)
    old.execute("PRAGMA user_version = 1")
    old.commit()
    old.close()
    errors = []

    def open_it():
        try:
            Store(path).close()
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=open_it) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    s = Store(path)
    assert s.conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    s.close()
