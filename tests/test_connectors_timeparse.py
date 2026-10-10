"""Deterministic event time parsing: English and romanized/Devanagari Marathi, Asia/Kolkata."""

from datetime import datetime

import pytest

from jarvis.connectors.config import get_tz
from jarvis.connectors.timeparse import TimeParseError, parse_iso, parse_when

TZ = get_tz("Asia/Kolkata")
NOW = datetime(2026, 10, 10, 15, 0, tzinfo=TZ)  # Saturday 3 pm


def at(text, now=NOW):
    p = parse_when(text, now, "Asia/Kolkata", 30)
    return p.start.strftime("%Y-%m-%d %H:%M"), p.end.strftime("%H:%M")


@pytest.mark.parametrize("text,start,end", [
    ("tomorrow at 11", "2026-10-11 11:00", "11:30"),
    ("Monday 5 pm", "2026-10-12 17:00", "17:30"),
    ("monday at 5pm for 1 hour", "2026-10-12 17:00", "18:00"),
    ("12 Oct 3pm for 45 minutes", "2026-10-12 15:00", "15:45"),
    ("Oct 20 at 11:30 am", "2026-10-20 11:30", "12:00"),
    ("15/10 11 am", "2026-10-15 11:00", "11:30"),
    ("2026-10-15 17:00", "2026-10-15 17:00", "17:30"),
    ("tomorrow 11 to 12:30 pm", "2026-10-11 11:00", "12:30"),
    ("tomorrow 3 to 4", "2026-10-11 15:00", "16:00"),
    ("noon tomorrow", "2026-10-11 12:00", "12:30"),
    ("tonight at 9", "2026-10-10 21:00", "21:30"),
    ("in 2 hours", "2026-10-10 17:00", "17:30"),
    ("next saturday 10 am", "2026-10-17 10:00", "10:30"),
    ("saturday 2 pm", "2026-10-17 14:00", "14:30"),   # passed today -> next week
    ("saturday 4 pm", "2026-10-10 16:00", "16:30"),   # still ahead today
])
def test_english(text, start, end):
    assert at(text) == (start, end)


@pytest.mark.parametrize("text,start,end", [
    ("udya 11 la", "2026-10-11 11:00", "11:30"),
    ("udya sakali 9 vajta", "2026-10-11 09:00", "09:30"),
    ("aaj sandhyakali 7", "2026-10-10 19:00", "19:30"),
    ("udya dupari 3 la", "2026-10-11 15:00", "15:30"),
    ("sade 10 udya", "2026-10-11 10:30", "11:00"),
    ("paune 11 udya", "2026-10-11 10:45", "11:15"),
    ("savva 9 udya sakali", "2026-10-11 09:15", "09:45"),
    ("parva 4 la", "2026-10-12 16:00", "16:30"),
    ("somvari 5 la 1 tas", "2026-10-12 17:00", "18:00"),
    ("pudhchya somvari 10 la", "2026-10-12 10:00", "10:30"),
    ("udya 11-12", "2026-10-11 11:00", "12:00"),
    ("udya ratri 9", "2026-10-11 21:00", "21:30"),
    ("उद्या ११ वाजता", "2026-10-11 11:00", "11:30"),
    ("उद्या सकाळी साडे ९", "2026-10-11 09:30", "10:00"),
])
def test_romanized_and_devanagari_marathi(text, start, end):
    assert at(text) == (start, end)


def test_guesses_are_listed_in_the_confirmation():
    p = parse_when("tomorrow at 11", NOW, "Asia/Kolkata")
    text = p.confirmation()
    assert text.startswith("Sunday 11 Oct 2026, 11:00 to 11:30 (Asia/Kolkata)")
    assert "read as am" in text and "length 30 minutes" in text
    assert "2026-10-11T11:00:00+05:30" in p.as_tool_text()


def test_time_only_rolls_to_tomorrow_when_passed():
    p = parse_when("at 9", NOW, "Asia/Kolkata")
    assert p.start.strftime("%Y-%m-%d %H:%M") == "2026-10-11 09:00"
    assert "passed today" in p.confirmation()


def test_bare_hour_1_to_6_is_pm():
    assert at("udya 4") == ("2026-10-11 16:00", "16:30")


def test_errors():
    with pytest.raises(TimeParseError, match="what time"):
        parse_when("tomorrow", NOW, "Asia/Kolkata")
    with pytest.raises(TimeParseError):
        parse_when("sometime soon", NOW, "Asia/Kolkata")
    with pytest.raises(TimeParseError):
        parse_when("31 feb 10 am", NOW, "Asia/Kolkata")


def test_timezone_is_configurable_and_naive_now_is_local():
    p = parse_when("tomorrow at 11 am", datetime(2026, 10, 10, 15, 0), "UTC")
    assert p.start.isoformat() == "2026-10-11T11:00:00+00:00"


def test_parse_iso_naive_uses_configured_zone():
    assert parse_iso("2026-10-11T11:00", "Asia/Kolkata").utcoffset().total_seconds() == 5.5 * 3600
    with pytest.raises(TimeParseError):
        parse_iso("tomorrow 11")
