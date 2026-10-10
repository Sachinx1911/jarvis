"""Weekly memory cleanup (PLAN.md 6.6): duplicates, relative dates, archiving, MEMORY.md, report, dry run.
Deterministic; synthetic memories in English, romanized Marathi and Devanagari."""

import argparse
import io
from datetime import date

import pytest

from jarvis import cli_memory
from jarvis.core.runtime import open_runtime
from jarvis.memory.maintenance import MemoryCleanup, normalize, resolve_relative_dates, similarity
from jarvis.memory.model import Memory
from jarvis.memory.store import MEMORY_INDEX_MAX_LINES
from jarvis.proactive.scheduler import ScheduleStore

from test_proactive_support import at, proactive

TODAY = date(2026, 10, 11)   # a Sunday
SETTINGS = {"duplicate_similarity": 0.9, "borderline_similarity": 0.75, "archive_after_days": 90,
            "keep_types": ["constraint", "preference"]}


@pytest.fixture
def rt():
    runtime = open_runtime()
    yield runtime
    runtime.close()


def _mem(rt, body, type="fact", subject="car", valid_from="2026-10-01", last_used="", **kw):
    return rt.memory.save(Memory(name=body[:40], type=type, subject=subject, body=body, evidence=body,
                                 valid_from=valid_from, last_used=last_used, **kw))


def _cleanup(rt, dry_run=False):
    return MemoryCleanup(rt.memory, rt.paths.home, TODAY, rt.audit, SETTINGS).run(dry_run=dry_run)


# ---- similarity ----

def test_similarity_is_deterministic_and_unicode_safe():
    assert normalize("  Car SERVICE, every 5000 km! ") == "car service every 5000 km"
    assert similarity("मला सकाळी चहा आवडतो", "मला सकाळी चहा आवडतो.") == 1.0
    assert similarity("Gym on Monday", "Gym on Tuesday") < 0.75


# ---- duplicates ----

def test_near_identical_duplicates_keep_the_newest_and_supersede_the_rest(rt):
    old = _mem(rt, "The car service is due every 5000 km at the Pune garage", valid_from="2026-09-01")
    mid = _mem(rt, "the car service is due every 5000 km at the Pune garage.", valid_from="2026-09-15")
    new = _mem(rt, "The car service is due every 5000 km at the Pune garage!", valid_from="2026-10-01")
    report = _cleanup(rt)
    assert sorted(o for o, k, s in report.superseded) == sorted([old.id, mid.id])
    assert {k for o, k, s in report.superseded} == {new.id}
    for m in (old, mid):
        got = rt.memory.get(m.id)                      # still there: superseded, never deleted
        assert got.status == "superseded" and got.superseded_by == new.id and got.valid_until == TODAY.isoformat()
    assert rt.memory.get(new.id).status == "active"


def test_devanagari_duplicates_are_merged(rt):
    a = _mem(rt, "मला सकाळी चहा आवडतो", type="preference", subject="user", valid_from="2026-08-01")
    b = _mem(rt, "मला सकाळी चहा आवडतो.", type="preference", subject="user", valid_from="2026-09-01")
    report = _cleanup(rt)
    assert report.superseded == [(a.id, b.id, 1.0)]


def test_different_type_or_subject_is_never_merged(rt):
    _mem(rt, "Service every 5000 km", subject="car")
    _mem(rt, "Service every 5000 km", subject="bike")
    _mem(rt, "Service every 5000 km", type="procedure", subject="car")
    assert _cleanup(rt).superseded == []


def test_borderline_pairs_are_reported_not_merged(rt):
    a = _mem(rt, "The car service is due every 5000 km at the Pune garage", valid_from="2026-09-01")
    b = _mem(rt, "The car service is due every 5000 km at the Nashik garage", valid_from="2026-10-01")
    report = _cleanup(rt)
    assert report.superseded == []
    assert [(x, y) for x, y, s in report.borderline] == [(b.id, a.id)]
    assert 0.75 <= report.borderline[0][2] < 0.9
    assert rt.memory.get(a.id).status == "active" and rt.memory.get(b.id).status == "active"
    assert f"{b.id} ~ {a.id}" in report.path.read_text(encoding="utf-8")


# ---- relative dates ----

@pytest.mark.parametrize("text, expected", [
    ("Dentist appointment tomorrow at 5", "Dentist appointment 2026-10-02 at 5"),
    ("Team call next Monday", "Team call 2026-10-05"),                  # 2026-10-01 is a Thursday
    ("Trip the day after tomorrow", "Trip 2026-10-03"),
    ("Pay rent in 3 days", "Pay rent 2026-10-04"),
    ("udya sakali bank madhe jaycha ahe", "2026-10-02 sakali bank madhe jaycha ahe"),
    ("pudhchya somvari parat ye", "2026-10-05 parat ye"),
    ("पुढच्या सोमवारी मीटिंग आहे", "2026-10-05 मीटिंग आहे"),
    ("उद्या डॉक्टरकडे जायचे", "2026-10-02 डॉक्टरकडे जायचे"),
    ("I read today's news first", "I read today's news first"),        # not a date
    ("kal bhetu", "kal bhetu"),                                           # ambiguous: left alone
    ("Gym on Monday", "Gym on Monday"),                                   # could be every Monday
    ("आजचा दिवस छान", "आजचा दिवस छान"),                                  # part of a longer word
])
def test_relative_dates_resolve_from_valid_from(text, expected):
    assert resolve_relative_dates(text, date(2026, 10, 1)) == expected


def test_next_weekday_said_on_that_weekday_is_a_week_later():
    assert resolve_relative_dates("next Monday", date(2026, 10, 5)) == "2026-10-12"


def test_cleanup_fixes_dates_and_keeps_the_original_in_evidence(rt):
    m = _mem(rt, "Dentist appointment tomorrow at 5", subject="health", summary_en="Dentist tomorrow at 5 pm.")
    report = _cleanup(rt)
    got = rt.memory.get(m.id)
    assert got.body == "Dentist appointment 2026-10-02 at 5" and got.summary_en == "Dentist 2026-10-02 at 5 pm."
    assert "original body: Dentist appointment tomorrow at 5" in got.evidence
    assert got.evidence.startswith("Dentist appointment tomorrow at 5")   # the user's quote stays first
    assert len(report.dates_fixed) == 2
    assert "2026-10-02" in (rt.memory.root / "MEMORY.md").read_text(encoding="utf-8")


# ---- archive ----

def test_unused_memories_are_archived_except_constraints_and_preferences(rt):
    stale_used = _mem(rt, "Old wifi router model is XR-100", subject="wifi", valid_from="2026-01-01",
                      last_used="2026-06-01")                               # last used 132 days ago
    never_used = _mem(rt, "Neighbour's dog is called Tiger", subject="dog", valid_from="2026-06-01")
    recent = _mem(rt, "Office moved to the third floor", subject="office", valid_from="2026-01-01",
                  last_used="2026-10-01")
    pref = _mem(rt, "Prefers short answers", type="preference", subject="style", valid_from="2025-01-01")
    rule = _mem(rt, "Never book flights before 7 am", type="constraint", subject="travel", valid_from="2025-01-01")
    report = _cleanup(rt)
    assert sorted(i for i, _ in report.archived) == sorted([stale_used.id, never_used.id])
    assert rt.memory.get(stale_used.id).status == "archived"
    for m in (recent, pref, rule):
        assert rt.memory.get(m.id).status == "active"


# ---- MEMORY.md, report, dry run ----

def test_memory_md_stays_under_200_lines(rt):
    folder = rt.memory.root / "facts"
    for i in range(1, 231):
        m = Memory(name=f"fact {i}", id=f"m-{i:04d}", body=f"synthetic fact number {i}", evidence=f"fact {i}",
                   subject=f"s{i}", valid_from="2026-10-01")
        (folder / f"{m.id}-fact-{i}.md").write_text(m.to_markdown(), encoding="utf-8")
    rt.memory.reindex()
    report = _cleanup(rt)
    assert report.memory_md_lines <= MEMORY_INDEX_MAX_LINES and not report.errors
    assert len((rt.memory.root / "MEMORY.md").read_text(encoding="utf-8").splitlines()) <= MEMORY_INDEX_MAX_LINES


def test_dry_run_changes_nothing_but_reports_everything(rt):
    a = _mem(rt, "Car insurance renews tomorrow", valid_from="2026-09-01")
    b = _mem(rt, "Car insurance renews tomorrow.", valid_from="2026-09-01")   # same day: the higher id is newer
    old = _mem(rt, "Old phone was a model Z1", subject="phone", valid_from="2026-01-01")
    files = {p: p.read_text(encoding="utf-8") for p in rt.memory.root.rglob("*.md")}
    report = _cleanup(rt, dry_run=True)
    assert {p: p.read_text(encoding="utf-8") for p in rt.memory.root.rglob("*.md")} == files
    assert report.dry_run and report.dates_fixed and [o for o, k, s in report.superseded] == [a.id]
    assert [i for i, _ in report.archived] == [old.id]
    assert report.path.name == "2026-10-11-dry-run.md" and "dry run" in report.path.read_text(encoding="utf-8")
    assert rt.memory.get(b.id).body == "Car insurance renews tomorrow."


def test_report_file_and_summary(rt):
    _mem(rt, "Car insurance renews tomorrow")
    report = _cleanup(rt)
    assert report.path == rt.paths.home / "data" / "maintenance" / "2026-10-11.md"
    text = report.path.read_text(encoding="utf-8")
    assert "1 relative date(s) fixed" in report.summary() and "## Archived (unused)" in text


# ---- CLI and schedule ----

def _args(action, dry_run=False):
    return argparse.Namespace(command="memory-maint", action=action, dry_run=dry_run)


def test_cli_run_and_report(rt):
    parser = argparse.ArgumentParser()
    handlers = cli_memory.register(parser.add_subparsers(dest="command"))
    assert set(handlers) == {"memory-maint"}
    args = parser.parse_args(["memory-maint", "run", "--dry-run"])
    _mem(rt, "Car insurance renews tomorrow")
    out = io.StringIO()
    assert handlers["memory-maint"](args, out, io.StringIO(), None, today=TODAY) == 0
    assert "dry run" in out.getvalue() and "2026-10-11-dry-run.md" in out.getvalue()
    out = io.StringIO()
    assert cli_memory.cmd_memory_maint(_args("report"), out, io.StringIO(), None) == 0
    assert "# Memory cleanup 2026-10-11 (dry run)" in out.getvalue()


def test_cli_report_without_any_report():
    out = io.StringIO()
    assert cli_memory.cmd_memory_maint(_args("report"), out, io.StringIO(), None) == 1


def test_weekly_cleanup_schedule_runs_on_sunday_evening():
    p = proactive(at(2026, 10, 10, 15, 0))
    p.ensure_default_schedules()
    rt = open_runtime()
    try:
        s = next(x for x in ScheduleStore(rt.store.conn).list() if x.kind == "memory_cleanup")
        assert s.next_run_at == "2026-10-11T21:00:00+05:30"
        _mem(rt, "Car insurance renews tomorrow")
    finally:
        rt.close()
    p.clock.now = at(2026, 10, 11, 21, 0)
    result = p.runner().run(s.id, "cron")
    assert result.status == "ok" and "1 relative date(s) fixed" in result.text
    assert "2026-10-11.md" in result.text
