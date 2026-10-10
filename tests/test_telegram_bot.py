"""Telegram bot, offline: allowed user only, approval buttons, /stop without a model, commands."""

import asyncio
import json
import threading
import time

import pytest
from telegram.ext import ApplicationHandlerStop, CallbackQueryHandler, CommandHandler

from jarvis.control.approvals import ApprovalRequest
from jarvis.control.stop import StopSwitch
from jarvis.core.runtime import open_runtime
from jarvis.proactive.cloud import cloud_override
from jarvis.proactive.scheduler import ScheduleStore
from jarvis.telegram.approvals import ApprovalBroker, TelegramApprover
from jarvis.telegram.bot import JarvisBot
from jarvis.telegram.core import BotCore

from test_proactive_support import FakeBot, ScriptedChats, at, button_data, proactive, update

SACHIN = 1111       # made-up ids
STRANGER = 2222


def _audit(home):
    path = home / "data" / "audit.jsonl"
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def _bot(chats=None, timeout=5.0, now=None):
    p = proactive(now or at(2026, 10, 10, 15, 0), chats or ScriptedChats())
    core = BotCore(p, SACHIN)
    return JarvisBot(core, approval_timeout=timeout, bot=FakeBot()), core


def test_bot_needs_an_allowed_user_id():
    with pytest.raises(ValueError):
        BotCore(proactive(at(2026, 10, 10, 15, 0)), 0)


# ---- only Sachin ----

def test_gate_drops_and_logs_strangers(isolated):
    bot, _ = _bot()
    u = update(STRANGER, "hello")
    with pytest.raises(ApplicationHandlerStop):
        asyncio.run(bot.gate(u, None))
    asyncio.run(bot.gate(update(SACHIN, "hello"), None))            # allowed: passes through
    rejected = [e for e in _audit(isolated) if e["event"] == "telegram_rejected"]
    assert rejected and rejected[0]["user_id"] == STRANGER
    assert "hello" not in json.dumps(rejected)                       # a stranger's text is not stored


def test_handlers_ignore_strangers_even_without_the_gate():
    chats = ScriptedChats(["should not run"])
    bot, _ = _bot(chats)
    u = update(STRANGER, "/stop")
    asyncio.run(bot.on_command(u, None))
    asyncio.run(bot.on_text(update(STRANGER, "hi"), None))
    assert u.effective_message.replies == [] and chats.calls == 0
    assert not StopSwitch(open_runtime().paths.data).engaged()


def test_application_builds_offline_with_gate_first():
    bot, _ = _bot()
    app = bot.build("123456:TEST-token-not-real")
    assert app.handlers[-1][0].callback == bot.gate
    names = {c for h in app.handlers[0] if isinstance(h, CommandHandler) for c in h.commands}
    assert {"stop", "resume", "tasks", "task", "schedules", "brief", "cloud", "approvals"} <= names
    assert any(isinstance(h, CallbackQueryHandler) for h in app.handlers[0])


# ---- /stop works outside the LLM loop ----

def test_stop_engages_without_any_model_call(isolated):
    def no_model(rt, approver):
        raise AssertionError("/stop must not build a chat session")
    bot, core = _bot()
    core.p.chat_factory = no_model
    u = update(SACHIN, "/stop phone said so")
    asyncio.run(bot.on_command(u, None))
    assert StopSwitch(isolated / "data").engaged()
    assert "Emergency stop ON" in u.effective_message.replies[0][0]
    u2 = update(SACHIN, "do something")
    asyncio.run(bot.on_text(u2, None))
    assert "Emergency stop is ON" in u2.effective_message.replies[0][0]
    asyncio.run(bot.on_command(update(SACHIN, "/resume"), None))
    assert not StopSwitch(isolated / "data").engaged()


def test_stop_denies_a_waiting_approval_at_once():
    broker = ApprovalBroker()
    bot, core = _bot()
    core.broker = broker
    approver = TelegramApprover(broker, lambda text, token: None, timeout=30)
    result = {}
    t = threading.Thread(target=lambda: result.setdefault("ok", approver(ApprovalRequest("delete_file", "T3",
                                                                                         {"path": "x"}, "r"))))
    t.start()
    while broker.waiting() == 0:
        time.sleep(0.01)
    started = time.monotonic()
    core.cmd_stop("now")
    t.join(5)
    assert result["ok"] is False and time.monotonic() - started < 2


# ---- approval buttons ----

def _approve_flow(answer: str | None, timeout: float = 5.0):
    """Chat turn asks for a T2 overwrite; the test presses a button (or not)."""
    chats = ScriptedChats([{"tool": "overwrite_file", "arguments": {"path": "notes.txt", "content": "new text"}},
                           "Done, sir."])
    bot, core = _bot(chats, timeout=timeout)
    rt = open_runtime()
    ws = rt.paths.home / "workspace"
    rt.close()
    (ws / "notes.txt").write_text("old text", encoding="utf-8")

    async def main():
        bot.loop = asyncio.get_running_loop()
        u = update(SACHIN, "replace my notes")
        task = asyncio.create_task(bot.on_text(u, None))
        for _ in range(500):
            if bot.bot.sent:
                break
            await asyncio.sleep(0.01)
        msg = bot.bot.sent[0]
        assert msg["chat_id"] == SACHIN
        assert '"path": "notes.txt"' in msg["text"] and '"content": "new text"' in msg["text"]  # exact arguments
        yes, no = button_data(msg["reply_markup"])
        q = None
        if answer is not None:
            q = update(SACHIN, data=yes if answer == "y" else no)
            await bot.on_callback(q, None)
        await asyncio.wait_for(task, 10)
        return u, q

    u, q = asyncio.run(main())
    bot.chat_pool.shutdown(wait=True)
    return (ws / "notes.txt").read_text(encoding="utf-8"), u, q, bot


def test_approve_button_runs_the_action():
    content, u, q, _ = _approve_flow("y")
    assert content == "new text"
    assert q.callback_query.edits[0].startswith("APPROVED: overwrite_file")
    assert u.effective_message.replies[-1][0] == "Done, sir."


def test_deny_button_blocks_the_action():
    content, _, q, _ = _approve_flow("n")
    assert content == "old text"
    assert q.callback_query.edits[0].startswith("DENIED")


def test_no_answer_times_out_as_deny():
    content, _, _, bot = _approve_flow(None, timeout=0.3)
    assert content == "old text"
    assert "TIMED OUT (denied)" in bot.bot.edited[0]["text"]


def test_stranger_cannot_press_the_button():
    broker = ApprovalBroker()
    bot, core = _bot()
    core.broker = broker
    token = broker.open(ApprovalRequest("delete_file", "T3", {"path": "x"}, "r"))
    asyncio.run(bot.on_callback(update(STRANGER, data=f"ap:{token}:y"), None))
    assert broker.wait(token, 0) is None                              # still unanswered


def test_forged_or_old_token_is_refused():
    bot, _ = _bot()
    q = update(SACHIN, data="ap:deadbeef:y")
    asyncio.run(bot.on_callback(q, None))
    assert "closed" in q.callback_query.edits[0]


def test_send_failure_means_deny():
    def broken(text, token):
        raise RuntimeError("network down")
    approver = TelegramApprover(ApprovalBroker(), broken, timeout=5)
    assert approver(ApprovalRequest("open_url", "T2", {"url": "https://example.com"}, "r")) is False


# ---- commands ----

def _cmd(bot, text):
    u = update(SACHIN, text)
    asyncio.run(bot.on_command(u, None))
    return u.effective_message.replies


def test_tasks_and_task_commands():
    bot, _ = _bot()
    from jarvis.tasks.store import TaskStore

    rt = open_runtime()
    TaskStore(rt.store, rt.paths.data / "tasks").create("Compare three laptops")
    rt.close()
    assert "t-001 [BACKLOG] Compare three laptops" in _cmd(bot, "/tasks")[0][0]
    detail = _cmd(bot, "/task t-001")[0][0]
    assert "Goal: Compare three laptops" in detail and "Model calls: 0" in detail
    assert "No task t-999" in _cmd(bot, "/task t-999")[0][0]
    assert "CANCELLED" in _cmd(bot, "/cancel t-001")[0][0]


def test_schedule_from_chat_shows_draft_and_saves_only_after_confirm():
    bot, _ = _bot()
    replies = _cmd(bot, "/schedule every Monday at 9 project summary")
    shown, markup = replies[0]
    assert "every Monday at 09:00" in shown and "Save this schedule?" in shown
    rt = open_runtime()
    assert ScheduleStore(rt.store.conn).list() == []                   # nothing saved yet
    rt.close()
    save, cancel = button_data(markup)
    q = update(SACHIN, data=save)
    asyncio.run(bot.on_callback(q, None))
    assert q.callback_query.edits[0].startswith("Saved as s-001")
    assert "s-001 [enabled] project summary" in _cmd(bot, "/schedules")[0][0]
    q2 = update(SACHIN, data=save)                                     # pressing Save twice saves once
    asyncio.run(bot.on_callback(q2, None))
    assert "expired" in q2.callback_query.edits[0]


def test_schedule_cancel_button_and_unclear_text():
    bot, _ = _bot()
    _, markup = _cmd(bot, "/schedule daily 8am weather")[0]
    q = update(SACHIN, data=button_data(markup)[1])
    asyncio.run(bot.on_callback(q, None))
    assert q.callback_query.edits[0] == "Not saved."
    shown, markup = _cmd(bot, "/schedule")[0]
    assert markup is None and "Say what and when" in shown


def test_schedule_pause_resume_delete_commands():
    bot, core = _bot()
    core.p.save(core.p.draft("every day at 21:00 work report", use_model=False))
    assert "paused" in _cmd(bot, "/schedule_pause s-001")[0][0]
    assert "[PAUSED]" in _cmd(bot, "/schedules")[0][0]
    assert "resumed" in _cmd(bot, "/schedule_resume s-001")[0][0]
    assert "deleted" in _cmd(bot, "/schedule_delete s-001")[0][0]
    assert "No schedules" in _cmd(bot, "/schedules")[0][0]


def test_cloud_command_writes_the_local_override():
    bot, _ = _bot()
    assert "OFF on this machine" in _cmd(bot, "/cloud off")[0][0]
    assert cloud_override() is False
    assert "as configured" in _cmd(bot, "/cloud on")[0][0]
    assert cloud_override() is None
    bot.chat_pool.shutdown(wait=True)


def test_cloud_off_blocks_chat_routing(isolated):
    bot, core = _bot()
    core.p.chat_factory = None             # real routing: claude_code is cloud
    core.p.provider_override = None
    _cmd(bot, "/cloud off")
    u = update(SACHIN, "hello")
    asyncio.run(bot.on_text(u, None))
    assert "No AI model is allowed right now" in u.effective_message.replies[0][0]
    bot.chat_pool.shutdown(wait=True)


def test_remind_and_brief_commands():
    bot, _ = _bot()
    assert "set for Sat 10 Oct 15:10: call back" in _cmd(bot, "/remind in 10 minutes call back")[0][0]
    assert "#1 Sat 10 Oct 15:10 call back" in _cmd(bot, "/reminders")[0][0]
    assert "could not read when" in _cmd(bot, "/remind sometime")[0][0]
    assert _cmd(bot, "/brief")[0][0].startswith("Good morning, sir.")


def test_approvals_command_lists_and_dismisses():
    chats = ScriptedChats([{"tool": "open_url", "arguments": {"url": "https://example.com"}}, "ok"])
    bot, core = _bot(chats)
    s = core.p.save(core.p.draft("every day at 21:00 open the dashboard", use_model=False))
    core.p.runner().run(s.id, "cron")
    listing = _cmd(bot, "/approvals")[0][0]
    assert "#1 from s-001" in listing and "open_url [T2]" in listing and "https://example.com" in listing
    assert "Dismissed #1" in _cmd(bot, "/dismiss 1")[0][0]
    assert "Nothing waiting" in _cmd(bot, "/approvals")[0][0]


def test_chat_message_goes_to_one_session():
    chats = ScriptedChats(["first answer", "second answer"])
    bot, _ = _bot(chats)
    for text, expect in (("one", "first answer"), ("two", "second answer")):
        u = update(SACHIN, text)
        asyncio.run(bot.on_text(u, None))
        assert u.effective_message.replies[0][0] == expect
    assert len(chats.providers) == 1          # same conversation
    assert "New conversation" in _cmd(bot, "/new")[0][0]
    bot.chat_pool.shutdown(wait=True)
