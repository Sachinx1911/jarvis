"""Schedule and reminder time phrases: rules for English and romanized Marathi, model fallback."""

import pytest

from jarvis.proactive.reminders import parse_reminder
from jarvis.proactive.schedule_parse import (
    CronError, ScheduleParseError, ScheduleParser, next_runs, normalize_cron,
)
from jarvis.proactive.timeparse import parse_once, parse_recurring
from jarvis.providers.fake import FakeProvider
from jarvis.routing.policy import RouteDecision

from test_proactive_support import at

PARSER = RouteDecision("schedule_parser", "fake", "fake-1", "low", "test")


@pytest.mark.parametrize("text,cron,rest", [
    ("Give me a project summary every Monday at 9", "0 9 * * mon", "Give me a project summary"),
    ("every day at 21:00", "0 21 * * *", ""),
    ("daily 8am", "0 8 * * *", ""),
    ("daily at 7:30 pm send the work report", "30 19 * * *", "send the work report"),
    ("every evening at 6 check the follow-up list", "0 18 * * *", "check the follow-up list"),
    ("every night at 9 today's work report", "0 21 * * *", "today's work report"),
    ("every weekday at 9:30 am standup notes", "30 9 * * mon-fri", "standup notes"),
    ("every Saturday and Sunday at 10 plan the week", "0 10 * * sat,sun", "plan the week"),
    ("every monday and thursday at 7pm gym check", "0 19 * * mon,thu", "gym check"),
    ("every month on the 1st at 10 rent check", "0 10 1 * *", "rent check"),
    ("every 30 minutes check the build", "*/30 * * * *", "check the build"),
    ("every 2 hours", "0 */2 * * *", ""),
    ("every hour", "0 * * * *", ""),
    # romanized Marathi
    ("roj sakali 8 la weather sang", "0 8 * * *", "weather sang"),
    ("roj ratri 9 vajta summary de", "0 21 * * *", "summary de"),
    ("dar somvari sandhyakali 6 la follow-up list", "0 18 * * mon", "follow-up list"),
    ("dar shukravari dupari 3 la report", "0 15 * * fri", "report"),
    ("dar tasala paani pi", "0 * * * *", "paani pi"),
    # Devanagari basics
    ("रोज सकाळी 8 वाजता हवामान", "0 8 * * *", "हवामान"),
    ("दर सोमवारी सकाळी 9 वाजता report", "0 9 * * mon", "report"),
])
def test_recurring_rules(text, cron, rest):
    got = parse_recurring(text)
    assert got is not None, text
    assert got.cron == cron
    assert got.rest == rest


@pytest.mark.parametrize("text", [
    "every Monday",            # no time: ask, do not guess
    "on Monday at 9 call",     # one-off, not a schedule
    "project summary",
    "every 90 minutes",        # does not fit a cron step cleanly
])
def test_recurring_rules_refuse_unclear_text(text):
    assert parse_recurring(text) is None


def test_rule_crons_are_valid_and_fire_on_the_right_day():
    # 2026-10-10 is a Saturday. "every Monday at 9" must next fire on Monday the 12th, 09:00 IST.
    cron = parse_recurring("every Monday at 9 x").cron
    runs = next_runs(cron, "Asia/Kolkata", at(2026, 10, 10, 15, 0))
    assert [r.isoformat() for r in runs[:2]] == ["2026-10-12T09:00:00+05:30", "2026-10-19T09:00:00+05:30"]


@pytest.mark.parametrize("expr,expected", [
    ("0 9 * * 1", "0 9 * * mon"),           # standard cron: 1 = Monday
    ("0 9 * * 0", "0 9 * * sun"),           # standard cron: 0 = Sunday (APScheduler would read Monday)
    ("0 9 * * 7", "0 9 * * sun"),
    ("0 9 * * 1-5", "0 9 * * mon,tue,wed,thu,fri"),
    ("0 9 * * MON-FRI", "0 9 * * mon-fri"),
    ("*/15 * * * *", "*/15 * * * *"),
])
def test_normalize_cron(expr, expected):
    assert normalize_cron(expr) == expected


@pytest.mark.parametrize("expr", ["0 9 * *", "0 9 * * */2", "61 9 * * *", "0 9 * * funday", "0 9 * * 5-1"])
def test_normalize_cron_rejects(expr):
    with pytest.raises(CronError):
        normalize_cron(expr)


# ---- model fallback (only for text the rules cannot read) ----

def test_rules_first_no_model_call():
    provider = FakeProvider()
    draft = ScheduleParser("Asia/Kolkata", provider, PARSER).parse("every Monday at 9 project summary")
    assert draft.source == "rules" and draft.cron == "0 9 * * mon" and draft.input == "project summary"
    assert provider.requests == []


def test_model_fallback_and_numeric_weekday_is_normalised():
    provider = FakeProvider(script=[{"json": {"cron": "0 9 * * 1", "what": "project summary",
                                              "summary": "every Monday at 09:00", "ambiguous": False,
                                              "question": ""}}])
    draft = ScheduleParser("Asia/Kolkata", provider, PARSER).parse("har aathavdyachya suruvatila project summary")
    assert draft.source == "model"
    assert draft.cron == "0 9 * * mon"
    assert len(provider.requests) == 1 and provider.requests[0].route == "schedule_parser"


def test_model_ambiguous_becomes_a_question():
    provider = FakeProvider(script=[{"json": {"cron": "", "what": "summary", "summary": "", "ambiguous": True,
                                              "question": "At what time on Mondays?"}}])
    with pytest.raises(ScheduleParseError) as e:
        ScheduleParser("Asia/Kolkata", provider, PARSER).parse("every Monday summary")
    assert e.value.question == "At what time on Mondays?"


def test_model_bad_cron_is_refused():
    provider = FakeProvider(script=[{"json": {"cron": "every monday", "what": "x", "summary": "", "ambiguous": False,
                                              "question": ""}}])
    with pytest.raises(ScheduleParseError):
        ScheduleParser("Asia/Kolkata", provider, PARSER).parse("sometime weekly x")


def test_without_model_unclear_text_asks():
    with pytest.raises(ScheduleParseError):
        ScheduleParser("Asia/Kolkata").parse("now and then")


def test_draft_show_lists_next_runs_and_safety_note():
    draft = ScheduleParser("Asia/Kolkata").parse("every day at 21:00 work report")
    shown = draft.show(at(2026, 10, 10, 15, 0))
    assert "every day at 21:00" in shown and "Sat 10 Oct 21:00" in shown and "T0/T1" in shown


# ---- one-off times (reminders) ----

NOW = at(2026, 10, 10, 15, 0)  # Saturday 15:00


@pytest.mark.parametrize("text,due,message", [
    ("remind me in 10 minutes to drink water", at(2026, 10, 10, 15, 10), "drink water"),
    ("in an hour stretch", at(2026, 10, 10, 16, 0), "stretch"),
    ("in half an hour check the oven", at(2026, 10, 10, 15, 30), "check the oven"),
    ("remind me tomorrow at 9 to call the bank", at(2026, 10, 11, 9, 0), "call the bank"),
    ("remind me tomorrow to water the plants", at(2026, 10, 11, 9, 0), "water the plants"),
    ("at 18:30 team call", at(2026, 10, 10, 18, 30), "team call"),
    ("at 9 standup", at(2026, 10, 11, 9, 0), "standup"),             # 9 has passed today
    ("on Friday at 5pm pay the bill", at(2026, 10, 16, 17, 0), "pay the bill"),
    ("on 2026-10-12 at 9 renew the parking pass", at(2026, 10, 12, 9, 0), "renew the parking pass"),
    ("tomorrow evening movie tickets", at(2026, 10, 11, 18, 0), "movie tickets"),
    # romanized Marathi
    ("10 minitani chaha", at(2026, 10, 10, 15, 10), "chaha"),
    ("2 tasani doodh aan", at(2026, 10, 10, 17, 0), "doodh aan"),
    ("udya sakali 8 la doctor la phone karaychi aathvan kar", at(2026, 10, 11, 8, 0), "doctor la phone karaychi"),
    ("aaj sandhyakali 6 la bhaji aan", at(2026, 10, 10, 18, 0), "bhaji aan"),
    ("उद्या सकाळी 8 वाजता औषध", at(2026, 10, 11, 8, 0), "औषध"),
])
def test_reminder_parse(text, due, message):
    got = parse_reminder(text, NOW)
    assert got is not None, text
    assert got.due == due
    assert got.text == message


@pytest.mark.parametrize("text", ["remind me to call", "call the bank", "in 10 minutes", "aaj sakali 8 la walk"])
def test_reminder_parse_refuses(text):
    # no time / no message / time already past today with an explicit "today"
    assert parse_reminder(text, NOW) is None


def test_once_needs_aware_now():
    assert parse_once("in 5 minutes x", NOW).due.tzinfo is not None
