from datetime import date

import pytest

from jarvis.memory.timefilter import DateRange, extract_range, has_time_cue, model_range
from jarvis.providers.fake import FakeProvider
from jarvis.routing.policy import RouteDecision

TODAY = date(2026, 10, 10)   # a Saturday
DECISION = RouteDecision("memory_extractor", "fake", "fake-1", "low", "test")


def _r(text):
    r = extract_range(text, TODAY)
    return (r.start.isoformat(), r.end.isoformat()) if r else None


@pytest.mark.parametrize("text, expected", [
    ("what did I say last week about the car", ("2026-09-28", "2026-10-04")),
    ("मागच्या आठवड्यात मी काय सांगितलं", ("2026-09-28", "2026-10-04")),
    ("gelya athavdyat gym madhe kay kela", ("2026-09-28", "2026-10-04")),
    ("this week", ("2026-10-05", "2026-10-10")),
    ("gelya mahinyat kay zala", ("2026-09-01", "2026-09-30")),
    ("मागच्या महिन्यात किती पुस्तकं घेतली", ("2026-09-01", "2026-09-30")),
    ("ya mahinyat", ("2026-10-01", "2026-10-10")),
    ("gelya varshi", ("2025-01-01", "2025-12-31")),
    ("aaj kay ahe", ("2026-10-10", "2026-10-10")),
    ("yesterday", ("2026-10-09", "2026-10-09")),
    ("day before yesterday", ("2026-10-08", "2026-10-08")),
    ("3 divsapurvi", ("2026-10-07", "2026-10-07")),
    ("३ दिवसांपूर्वी काय झालं", ("2026-10-07", "2026-10-07")),
    ("2 weeks ago", ("2026-09-23", "2026-09-29")),
    ("last 10 days", ("2026-09-30", "2026-10-10")),
    ("on 14 September", ("2026-09-14", "2026-09-14")),
    ("Sept 14 2025", ("2025-09-14", "2025-09-14")),
    ("14/09/2026", ("2026-09-14", "2026-09-14")),
    ("2026-09-14 la", ("2026-09-14", "2026-09-14")),
    ("on 20 December", ("2025-12-20", "2025-12-20")),          # a future date means last year's
    ("सप्टेंबरमध्ये", ("2026-09-01", "2026-09-30")),
    ("in May", ("2026-05-01", "2026-05-31")),
    ("last monday", ("2026-10-05", "2026-10-05")),
    ("somvari kay zala", ("2026-10-05", "2026-10-05")),
    ("recently", ("2026-09-26", "2026-10-10")),
    ("नुकतंच", ("2026-09-26", "2026-10-10")),
])
def test_deterministic_ranges(text, expected):
    assert _r(text) == expected


@pytest.mark.parametrize("text", ["tell me a joke", "may I ask something", "give me 5 ideas", "hello me", "",
                                  "where is my office"])
def test_no_range_without_a_time(text):
    assert _r(text) is None


def test_kal_and_parva_are_past_unless_future_tense():
    assert _r("kal mi kay khalla") == ("2026-10-09", "2026-10-09")
    assert _r("काल डॉक्टरकडे गेलो") == ("2026-10-09", "2026-10-09")
    assert _r("kal kay karnar ahes") == ("2026-10-11", "2026-10-11")     # -nar verb: tomorrow
    assert _r("parva") == ("2026-10-08", "2026-10-08")
    assert _r("parva yenar ahe") == ("2026-10-12", "2026-10-12")


def test_time_words_are_reported_for_removal():
    r = extract_range("gelya mahinyat gym madhe kay", TODAY)
    assert {"gelya", "mahinyat"} <= r.words and "gym" not in r.words
    assert {"march", "madhe"} <= extract_range("march madhe", TODAY).words


def test_range_helpers():
    r = DateRange(date(2026, 9, 1), date(2026, 9, 30))
    assert r.contains_iso("2026-09-15") and not r.contains_iso("2026-10-01") and not r.contains_iso("")
    lo, hi = r.utc_bounds()
    assert len(lo) == len(hi) == 19 and lo < hi
    assert r.contains_utc_ts("2026-09-15 10:00:00")


def test_model_step_only_when_rules_miss_and_a_cue_exists():
    provider = FakeProvider(script=[{"json": {"has_time": True, "start": "2026-08-10", "end": "2026-08-20"}}])
    r = model_range("when did I meet the plumber before the festival", TODAY, provider, DECISION)
    assert (r.start, r.end, r.label) == (date(2026, 8, 10), date(2026, 8, 20), "model")
    assert provider.requests[0].route == "memory_extractor"

    quiet = FakeProvider()
    assert model_range("gelya athavdyat", TODAY, quiet, DECISION).label == "last_week"   # rules first
    assert model_range("where is my office", TODAY, quiet, DECISION) is None            # no cue
    assert quiet.requests == []
    assert has_time_cue("kevha ala") and not has_time_cue("office kuthe")


def test_model_step_rejects_bad_output():
    for item in ({"json": {"has_time": True, "start": "x", "end": "2026-08-20"}},
                 {"json": {"has_time": True, "start": "2026-08-20", "end": "2026-08-10"}},
                 {"json": {"has_time": False, "start": "", "end": ""}},
                 "not json"):
        assert model_range("when was it", TODAY, FakeProvider(script=[item]), DECISION) is None
    assert model_range("when was it", TODAY, None, None) is None
