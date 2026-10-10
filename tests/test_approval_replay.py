"""Approving actions that unattended schedule runs queued: exact replay once, deny, mismatch, stale, T4.
Offline: fake provider, fake clock, fake notifier, fake Telegram."""

import argparse
import asyncio
import io
import json
from datetime import timedelta

from jarvis import cli_proactive
from jarvis.control.approvals import ApprovalGate, ApprovalRequest
from jarvis.control.stop import StopSwitch
from jarvis.core.runtime import open_runtime
from jarvis.proactive.replay import args_sha256, exact_approver
from jarvis.proactive.schedule_parse import ScheduleDraft
from jarvis.proactive.scheduler import PendingApprovals
from jarvis.providers.base import ToolSpec
from jarvis.telegram.bot import JarvisBot
from jarvis.telegram.core import BotCore
from jarvis.tools.registry import Tool, ToolRegistry

from test_proactive_support import FakeBot, FakeNotifier, ScriptedChats, at, button_data, proactive, update

NOW = at(2026, 10, 12, 9, 0)
SACHIN = 1111


def _audit(home):
    path = home / "data" / "audit.jsonl"
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def _queued(isolated, note=None, extra_script=()):
    """An unattended run that wanted to overwrite notes.txt (T2): queued, not run."""
    ws = isolated / "workspace"
    ws.mkdir(exist_ok=True)
    (ws / "notes.txt").write_text("original", encoding="utf-8")
    chats = ScriptedChats([{"tool": "overwrite_file", "arguments": {"path": "notes.txt", "content": "changed"}},
                           "Done what I could."], *extra_script)
    p = proactive(NOW, chats, note)
    s = p.save(ScheduleDraft(name="tidy notes", kind="prompt", input="tidy notes", cron="0 9 * * mon",
                             timezone="Asia/Kolkata", description="test"))
    assert p.runner().run(s.id, "cron").pending == 1
    assert (ws / "notes.txt").read_text(encoding="utf-8") == "original"
    return p, ws, chats


def _item(pid=1):
    rt = open_runtime()
    try:
        return PendingApprovals(rt.store.conn).get(pid)
    finally:
        rt.close()


# ---- approve ----

def test_approve_runs_the_exact_call_once_and_records_the_result(isolated):
    note = FakeNotifier()
    p, ws, chats = _queued(isolated, note)
    p.clock.now = NOW + timedelta(hours=2)
    r = p.approve_pending(1, source="telegram")
    assert r.status == "executed" and r.ok and r.verified is True
    assert (ws / "notes.txt").read_text(encoding="utf-8") == "changed"
    item = _item()
    assert item["status"] == "executed" and item["ok"] == 1 and item["verified"] == 1 and "[verified:" in item["result"]
    assert note.sent[-1][0] == "Approval" and "Approved #1: overwrite_file ran, verified" in note.sent[-1][1]
    events = [e["event"] for e in _audit(isolated)]
    assert "pending_approval_approved" in events and "pending_approval_replayed" in events
    assert chats.calls == 2                                          # replay made no model call
    # a second approval (double click, second device) does nothing
    (ws / "notes.txt").write_text("edited by hand", encoding="utf-8")
    assert p.approve_pending(1).status == "not_pending"
    assert (ws / "notes.txt").read_text(encoding="utf-8") == "edited by hand"


def test_deny_never_runs_and_cannot_be_approved_later(isolated):
    p, ws, _ = _queued(isolated)
    assert p.deny_pending(1).status == "denied"
    assert _item()["status"] == "denied"
    assert p.approve_pending(1).status == "not_pending"
    assert (ws / "notes.txt").read_text(encoding="utf-8") == "original"
    assert p.deny_pending(99).status == "unknown"


# ---- mismatch ----

def test_exact_approver_says_yes_only_to_the_same_tool_and_arguments():
    args = {"path": "notes.txt", "content": "changed"}
    ok = exact_approver("overwrite_file", args)
    assert not ok(ApprovalRequest("overwrite_file", "T2", {"path": "notes.txt", "content": "other"}, "x"))
    assert not ok(ApprovalRequest("delete_file", "T3", args, "x"))
    assert ok(ApprovalRequest("overwrite_file", "T2", {"content": "changed", "path": "notes.txt"}, "x"))  # key order
    assert not ok(ApprovalRequest("overwrite_file", "T2", args, "x"))                    # once only
    assert args_sha256({"b": 1, "a": "ā"}) == args_sha256({"a": "ā", "b": 1})


def test_any_other_approval_during_the_replay_is_denied(isolated):
    """A tool that asks for a second, different action while it runs: that one is refused."""
    p, ws, _ = _queued(isolated)
    seen = {}

    def factory(rt, approver):
        reg = ToolRegistry(rt.store, rt.audit, ApprovalGate(rt.store, rt.audit, approver))

        def overwrite(args):
            seen["nested"] = reg.gate.check("delete_file", "T3", {"path": "notes.txt"}, False, None)
            (ws / args["path"]).write_text(args["content"], encoding="utf-8")
            return "overwritten"
        spec = ToolSpec("overwrite_file", "test", {"type": "object", "properties": {
            "path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]})
        reg.register(Tool(spec, "T2", overwrite))
        return reg

    p.replay_registry = factory
    r = p.approve_pending(1)
    assert r.status == "executed"
    assert seen["nested"] == (False, "denied by user")
    assert (ws / "notes.txt").read_text(encoding="utf-8") == "changed"
    assert any(e["event"] == "replay_mismatch_denied" and e["tool"] == "delete_file" for e in _audit(isolated))


def test_stored_arguments_that_no_longer_match_the_tool_are_not_run(isolated):
    p, ws, _ = _queued(isolated)
    rt = open_runtime()
    rt.store.conn.execute("UPDATE sched_pending_approvals SET arguments=? WHERE id=1",
                          (json.dumps({"path": "notes.txt"}),))                   # content missing: invalid
    rt.store.conn.commit()
    rt.close()
    r = p.approve_pending(1)
    assert r.status == "failed" and not r.ok
    assert _item()["status"] == "failed"
    assert (ws / "notes.txt").read_text(encoding="utf-8") == "original"


# ---- stale, T4, stop ----

def test_stale_items_cannot_be_approved(isolated):
    p, ws, _ = _queued(isolated)
    p.clock.now = NOW + timedelta(hours=25)
    r = p.approve_pending(1)
    assert r.status == "stale" and "older than 24 h" in r.message
    assert _item()["status"] == "stale"
    assert (ws / "notes.txt").read_text(encoding="utf-8") == "original"


def test_stale_window_is_configurable(isolated):
    p, ws, _ = _queued(isolated)
    p.settings.raw["approvals"] = {"replay_max_age_hours": 1}
    p.clock.now = NOW + timedelta(hours=2)
    assert p.approve_pending(1).status == "stale"


def test_t4_items_never_run(isolated):
    p = proactive(NOW, ScriptedChats())
    rt = open_runtime()
    pid = PendingApprovals(rt.store.conn).add("s-001", 1, ApprovalRequest(
        "read_file", "T4", {"path": "../.env"}, "prohibited"), NOW)
    rt.close()
    called = []
    p.replay_registry = lambda rt, approver: called.append(1)
    r = p.approve_pending(pid)
    assert r.status == "refused" and called == []
    assert _item(pid)["status"] == "refused"
    assert any(e["event"] == "pending_approval_refused" for e in _audit(isolated))


def test_a_tool_that_became_t4_is_blocked_by_the_gate(isolated):
    p, ws, _ = _queued(isolated)

    def factory(rt, approver):
        reg = ToolRegistry(rt.store, rt.audit, ApprovalGate(rt.store, rt.audit, approver))
        spec = ToolSpec("overwrite_file", "test", {"type": "object", "properties": {}})
        reg.register(Tool(spec, "T4", lambda a: "should not run"))
        return reg

    p.replay_registry = factory
    r = p.approve_pending(1)
    assert r.status == "failed" and "prohibited" in r.message
    assert (ws / "notes.txt").read_text(encoding="utf-8") == "original"


def test_emergency_stop_blocks_replay(isolated):
    p, ws, _ = _queued(isolated)
    StopSwitch(isolated / "data").engage("test")
    assert p.approve_pending(1).status == "stopped"
    assert _item()["status"] == "pending"                           # still there for later
    StopSwitch(isolated / "data").release()
    assert p.approve_pending(1).status == "executed"


# ---- Telegram and CLI ----

def test_telegram_buttons_approve_and_deny(isolated):
    note = FakeNotifier()
    p, ws, _ = _queued(isolated, note)
    core = BotCore(p, SACHIN)
    bot = JarvisBot(core, approval_timeout=5, bot=FakeBot())
    u = update(SACHIN, "/approvals")
    asyncio.run(bot.on_command(u, None))
    replies = u.effective_message.replies
    assert "#1 from s-001" in replies[0][0] and "/approve <id>" in replies[0][0]
    assert button_data(replies[1][1]) == ["pa:1:y", "pa:1:n"]
    cb = update(SACHIN, data="pa:1:y")
    asyncio.run(bot.on_callback(cb, None))
    assert "Approved #1: overwrite_file ran" in cb.callback_query.edits[0]
    assert (ws / "notes.txt").read_text(encoding="utf-8") == "changed"
    assert "Nothing waiting" in _cmd(bot, "/approvals")
    assert "already executed" in _cmd(bot, "/deny 1")
    assert "Usage" in _cmd(bot, "/approve abc")
    bot.chat_pool.shutdown(wait=True)


def _cmd(bot, text):
    u = update(SACHIN, text)
    asyncio.run(bot.on_command(u, None))
    return u.effective_message.replies[0][0]


def test_telegram_deny_command(isolated):
    p, ws, _ = _queued(isolated)
    bot = JarvisBot(BotCore(p, SACHIN), approval_timeout=5, bot=FakeBot())
    assert "Denied #1" in _cmd(bot, "/deny 1")
    assert _item()["status"] == "denied"
    bot.chat_pool.shutdown(wait=True)


def _cli(p, monkeypatch, *argv, answer=""):
    monkeypatch.setattr(cli_proactive, "_proactive", lambda args, out, notify=True: p)
    parser = argparse.ArgumentParser()
    cli_proactive.register(parser.add_subparsers(dest="command"))
    out = io.StringIO()
    code = cli_proactive.handle(parser.parse_args(list(argv)), out, io.StringIO(answer + "\n"))
    return code, out.getvalue()


def test_cli_approve_asks_then_runs(isolated, monkeypatch):
    p, ws, _ = _queued(isolated)
    code, text = _cli(p, monkeypatch, "schedule", "approvals", "approve", "1", answer="n")
    assert code == 0 and "Not run; still pending" in text and '"content": "changed"' in text
    assert (ws / "notes.txt").read_text(encoding="utf-8") == "original"
    code, text = _cli(p, monkeypatch, "schedule", "approvals", "approve", "1", answer="y")
    assert code == 0 and "Approved #1: overwrite_file ran" in text
    assert (ws / "notes.txt").read_text(encoding="utf-8") == "changed"
    code, text = _cli(p, monkeypatch, "schedule", "approvals", "deny", "1")
    assert code == 1 and "already executed" in text


def test_cli_deny(isolated, monkeypatch):
    p, ws, _ = _queued(isolated)
    code, text = _cli(p, monkeypatch, "schedule", "approvals", "deny", "#1")
    assert code == 0 and "Denied #1" in text
    code, text = _cli(p, monkeypatch, "schedule", "approvals", "approve", "x")
    assert code == 2
