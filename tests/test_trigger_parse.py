"""Trigger parsing (English, romanized and Devanagari Marathi), parse-then-confirm in the CLI
and on Telegram. Offline; made-up addresses and links."""

from __future__ import annotations

import argparse
import asyncio
import io

import pytest

from jarvis import cli_proactive
from jarvis.core.runtime import open_runtime
from jarvis.proactive.trigger_parse import TriggerParseError, parse_amount, parse_trigger
from jarvis.proactive.triggers import TriggerStore
from jarvis.telegram.bot import JarvisBot
from jarvis.telegram.core import BotCore

from test_proactive_support import FakeBot, at, button_data, update
from test_triggers import STORE_URL, FakeWeb, make

SACHIN = 1111


@pytest.mark.parametrize("text, source, condition, action, task", [
    ("when a new file arrives in workspace/inbox summarize it", "file_new",
     {"folder": "workspace/inbox", "glob": "*"}, "prompt", "summarize it"),
    ("when a new file arrives in workspace/inbox, then summarize it", "file_new",
     {"folder": "workspace/inbox", "glob": "*"}, "prompt", "summarize it"),
    ("workspace/inbox madhe navin file aali tar summarize kar", "file_new",
     {"folder": "workspace/inbox", "glob": "*"}, "prompt", "summarize kar"),
    ("जर inbox मध्ये नवीन फाइल आली तर सारांश लिही", "file_new", {"folder": "inbox", "glob": "*"}, "prompt", "सारांश लिही"),
    ("when a new pdf file is added to inbox, tell me", "file_new", {"folder": "inbox", "glob": "*.pdf"}, "notify", ""),
    ("when I get an email from boss@example.com tell me", "email_from",
     {"sender": "boss@example.com", "subject": ""}, "notify", ""),
    ("boss@example.com kadun email aala tar sang", "email_from", {"sender": "boss@example.com", "subject": ""},
     "notify", ""),
    ("जर boss@example.com कडून ईमेल आला तर सांग", "email_from", {"sender": "boss@example.com", "subject": ""},
     "notify", ""),
    ("when an email with subject invoice arrives, tell me", "email_from", {"sender": "", "subject": "invoice"},
     "notify", ""),
    ("15 minutes before a meeting remind me", "calendar_soon", {"minutes": 15, "title": ""}, "notify", ""),
    ("notify me when a meeting starts within 10 minutes", "calendar_soon", {"minutes": 10, "title": ""}, "notify", ""),
    ("tell me when there are new results for 'new laptop launch India'", "web_search_new",
     {"query": "new laptop launch India", "topic": "general"}, "notify", ""),
    ("new laptop launch India baddal navin batmi aali tar sang", "web_search_new",
     {"query": "new laptop launch India", "topic": "news"}, "notify", ""),
])
def test_parse_examples(text, source, condition, action, task):
    d = parse_trigger(text)
    assert (d.source, d.condition, d.action, d.input) == (source, condition, action, task)
    assert d.read_by == "rules"


def test_parse_price_marathi_and_english():
    d = parse_trigger(f"jar laptop chi kimmat 75000 khali geli tar sang {STORE_URL}")
    assert d.source == "web_price" and d.action == "notify"
    assert d.condition == {"url": STORE_URL, "below": 75000.0, "product": "laptop"}
    d = parse_trigger(f"when the price of HP Victus 15 drops below Rs 72,500 notify me {STORE_URL}")
    assert d.condition["below"] == 72500.0 and d.condition["product"] == "HP Victus 15"
    d = parse_trigger(f"जर laptop ची किंमत 70 हजार खाली गेली तर सांग {STORE_URL}")
    assert d.condition["below"] == 70000.0


def test_parse_amounts():
    assert parse_amount("under 75k") == 75000
    assert parse_amount("below Rs 1,24,990 for 15 inch") == 124990
    assert parse_amount("1.2 lakh") == 120000
    assert parse_amount("nothing") is None


@pytest.mark.parametrize("text, asks", [
    ("hello there", "could not tell what to watch"),
    ("tell me when the price drops below 60000", "store page link"),
    (f"tell me when the price drops {STORE_URL}", "Below what price"),
    ("when I get an email tell me", "From whom"),
    ("when a new file arrives tell me", "Which folder"),
    ("", "Say what to watch"),
])
def test_unclear_text_becomes_a_question(text, asks):
    with pytest.raises(TriggerParseError) as e:
        parse_trigger(text)
    assert asks in e.value.question


def test_show_explains_what_runs():
    d = parse_trigger("when I get an email from boss@example.com tell me")
    shown = d.show()
    assert "email text itself is never passed on" in shown and "T0/T1" in shown and "noted first" in shown


# ---------------------------------------------------------------- CLI: parse, show, confirm, save


def _cli(p, monkeypatch, *argv, answer=""):
    monkeypatch.setattr(cli_proactive, "_proactive", lambda args, out, notify=True: p)
    parser = argparse.ArgumentParser()
    cli_proactive.register(parser.add_subparsers(dest="command"))
    out = io.StringIO()
    code = cli_proactive.handle(parser.parse_args(list(argv)), out, io.StringIO(answer + "\n"))
    return code, out.getvalue()


def _count():
    rt = open_runtime()
    try:
        return len(TriggerStore(rt.store.conn).list())
    finally:
        rt.close()


def test_cli_add_shows_draft_and_saves_only_after_yes(isolated, monkeypatch):
    (isolated / "workspace" / "inbox").mkdir(parents=True)
    p = make(at(2026, 10, 10, 10, 0))
    code, text = _cli(p, monkeypatch, "trigger", "add", "when a new file arrives in workspace/inbox summarize it",
                      answer="n")
    assert code == 0 and "Watches: file_new" in text and "Not saved" in text and _count() == 0
    code, text = _cli(p, monkeypatch, "trigger", "add", "when a new file arrives in workspace/inbox summarize it",
                      answer="y")
    assert code == 0 and "Saved as t-001" in text and _count() == 1
    code, text = _cli(p, monkeypatch, "trigger", "list")
    assert "t-001 [enabled] new or changed file in workspace/inbox -> prompt: summarize it" in text


def test_cli_refuses_amazon_with_reason(isolated, monkeypatch):
    p = make(at(2026, 10, 10, 10, 0))
    code, text = _cli(p, monkeypatch, "trigger", "add",
                      "jar laptop chi kimmat 75000 khali geli tar sang https://www.amazon.in/dp/B0TEST", "--yes")
    assert code == 1 and "terms forbid" in text and _count() == 0


def test_cli_question_when_unclear(isolated, monkeypatch):
    p = make(at(2026, 10, 10, 10, 0))
    code, text = _cli(p, monkeypatch, "trigger", "add", "hello there", "--yes")
    assert code == 1 and "could not tell" in text


def test_cli_kind_skill_and_every_flags(isolated, monkeypatch):
    (isolated / "workspace" / "inbox").mkdir(parents=True)
    p = make(at(2026, 10, 10, 10, 0))
    code, text = _cli(p, monkeypatch, "trigger", "add", "when a new file arrives in workspace/inbox",
                      "--kind", "skill", "--target", "file-sorter", "--every", "10", "--cooldown", "0", "--yes")
    assert code == 0, text
    rt = open_runtime()
    t = TriggerStore(rt.store.conn).get("t-001")
    rt.close()
    assert (t.action, t.target, t.every_s, t.cooldown_s) == ("skill", "file-sorter", 600, 0)


def test_cli_pause_resume_test_runs_delete(isolated, monkeypatch):
    inbox = isolated / "workspace" / "inbox"
    inbox.mkdir(parents=True)
    (inbox / "a.txt").write_text("a", encoding="utf-8")
    p = make(at(2026, 10, 10, 10, 0))
    _cli(p, monkeypatch, "trigger", "add", "when a new file arrives in workspace/inbox tell me", "--yes")
    code, text = _cli(p, monkeypatch, "trigger", "test", "t-001")
    assert code == 0 and "1 new" in text and "would only be noted" in text and "dry run" in text
    rt = open_runtime()
    assert TriggerStore(rt.store.conn).get("t-001").state == {}     # dry run changed nothing
    rt.close()
    code, text = _cli(p, monkeypatch, "trigger", "test", "t-001", "--fire")
    assert code == 0 and "baseline" in text
    code, text = _cli(p, monkeypatch, "trigger", "pause", "t-001")
    assert code == 0 and "[PAUSED]" in _cli(p, monkeypatch, "trigger", "list")[1]
    _cli(p, monkeypatch, "trigger", "resume", "t-001")
    assert "[enabled]" in _cli(p, monkeypatch, "trigger", "list")[1]
    code, text = _cli(p, monkeypatch, "trigger", "runs", "t-001")
    assert code == 0
    code, text = _cli(p, monkeypatch, "trigger", "delete", "t-001", answer="n")
    assert "Kept" in text and _count() == 1
    code, text = _cli(p, monkeypatch, "trigger", "delete", "t-001", answer="y")
    assert _count() == 0
    code, text = _cli(p, monkeypatch, "trigger", "pause", "t-009")
    assert code == 1 and "No trigger t-009" in text


def test_trigger_is_a_registered_cli_command():
    assert "trigger" in cli_proactive.COMMANDS


# ---------------------------------------------------------------- Telegram


def _cmd(bot, text):
    u = update(SACHIN, text)
    asyncio.run(bot.on_command(u, None))
    return u.effective_message.replies


def test_telegram_trigger_draft_save_and_list(isolated):
    (isolated / "workspace" / "inbox").mkdir(parents=True)
    p = make(at(2026, 10, 10, 10, 0))
    bot = JarvisBot(BotCore(p, SACHIN), approval_timeout=5, bot=FakeBot())
    [(shown, markup)] = _cmd(bot, "/trigger when a new file arrives in workspace/inbox summarize it")
    assert "Save this trigger?" in shown and _count() == 0
    data = button_data(markup)
    assert data[0].startswith("tr:") and data[0].endswith(":y")
    q = update(SACHIN, data=data[0])
    asyncio.run(bot.on_callback(q, None))
    assert "Saved as t-001" in q.callback_query.edits[0] and _count() == 1
    q = update(SACHIN, data=data[0])                                 # second click: draft is gone
    asyncio.run(bot.on_callback(q, None))
    assert "expired" in q.callback_query.edits[0] and _count() == 1
    [(listing, _)] = _cmd(bot, "/triggers")
    assert "t-001 [enabled]" in listing
    [(reply, _)] = _cmd(bot, "/trigger_pause t-001")
    assert "paused" in reply
    [(reply, _)] = _cmd(bot, "/trigger_delete t-001")
    assert "deleted" in reply and _count() == 0
    bot.chat_pool.shutdown(wait=True)


def test_telegram_cancel_and_refusal_and_email_privacy(isolated):
    p = make(at(2026, 10, 10, 10, 0), web=FakeWeb())
    bot = JarvisBot(BotCore(p, SACHIN), approval_timeout=5, bot=FakeBot())
    [(shown, markup)] = _cmd(bot, "/trigger when I get an email from boss@example.com tell me")
    no = button_data(markup)[1]
    q = update(SACHIN, data=no)
    asyncio.run(bot.on_callback(q, None))
    assert q.callback_query.edits[0] == "Not saved." and _count() == 0
    [(reply, markup)] = _cmd(bot, "/trigger tell me when the price drops below 50000 https://www.flipkart.com/x/p/itm1")
    assert "terms forbid" in reply and markup is None
    p.save_trigger(p.draft_trigger("when I get an email from boss@example.com tell me"))
    [(listing, _)] = _cmd(bot, "/triggers")
    assert "email rule t-001" in listing and "boss@example.com" not in listing
    bot.chat_pool.shutdown(wait=True)
