import json

from jarvis.control.audit import REDACTED, AuditLog
from jarvis.db import SCHEMA_VERSION, Store
from jarvis.providers.base import Message, ToolCall


def test_audit_redacts_secrets(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    log.write("x", api_key="abc", nested={"Authorization": "Bearer z"}, note="key sk-ant-abc123 leaked")
    record = json.loads((tmp_path / "audit.jsonl").read_text(encoding="utf-8"))
    assert record["api_key"] == REDACTED
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
