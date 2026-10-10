"""Global daily cap, runaway guard, nightly review and memory conflicts.

All data is synthetic. Times are IST (the proactive timezone in tests).
"""

from __future__ import annotations

import io
from datetime import timedelta

from jarvis.cli import main as cli_main
from jarvis.core.runtime import open_runtime
from jarvis.memory.conflicts import find_conflicts
from jarvis.memory.model import Memory
from jarvis.proactive.guard import (
    DailyCap, UnattendedGuard, cap_notice, consecutive_failures, usage_today,
)
from jarvis.proactive.review import MemoryConflictsSection, episode_path, nightly_review
from jarvis.proactive.brief import BriefContext
from jarvis.proactive.schedule_parse import ScheduleDraft
from jarvis.proactive.scheduler import ScheduleRunner, ScheduleStore
from jarvis.proactive.triggers import TriggerStore

from test_proactive_support import Clock, FakeNotifier, ScriptedChats, at, proactive
from test_triggers import TRIG, FakeWeb

NOW = at(2026, 10, 12, 21, 0)
CAP = {"daily_cap": {"max_model_calls": 3}, "pause_after_failures": 3}


def _draft(name="project summary", kind="prompt", cron="0 9 * * *"):
    return ScheduleDraft(name=name, kind=kind, input=name, cron=cron, timezone="Asia/Kolkata",
                         description="test", output="telegram")


def _prior_run(calls: int, when=NOW - timedelta(hours=2), sid="s-old"):
    rt = open_runtime()
    try:
        store = ScheduleStore(rt.store.conn)
        run_id = store.start_run(sid, "cron", when)
        store.finish_run(run_id, sid, "ok", "earlier work", when, calls=calls, usd=0.01 * calls)
    finally:
        rt.close()


# ---------------------------------------------------------------- unit


def test_consecutive_failures_ignores_skips_and_stops_at_success():
    assert consecutive_failures(["failed", "budget", "failed"]) == 3
    assert consecutive_failures(["failed", "skipped_overlap", "missed", "failed", "ok", "failed"]) == 2
    assert consecutive_failures(["ok", "failed", "failed"]) == 0
    assert consecutive_failures([]) == 0


def test_cap_from_settings_and_inactive_by_default():
    assert not DailyCap.from_settings({}).active()
    cap = DailyCap.from_settings({"max_runs": 10, "max_model_calls": 0, "max_notional_usd": "2.5"})
    assert cap.max_runs == 10 and cap.max_model_calls is None and cap.max_notional_usd == 2.5
    assert UnattendedGuard.from_settings(None).over_cap(None, NOW) is None  # inactive: no database needed


def test_usage_counts_only_today_and_only_runs_with_model_calls():
    _prior_run(2)
    _prior_run(0)                                    # a quiet check: costs nothing, not a "run"
    _prior_run(5, when=NOW - timedelta(days=1))      # yesterday
    rt = open_runtime()
    try:
        TriggerStore(rt.store.conn)                  # creates the trigger tables
        rt.store.conn.execute("INSERT INTO trig_fires (trigger_id, started_at, status, model_calls) "
                              "VALUES ('t-1', ?, 'ok', 4)", ((NOW - timedelta(hours=1)).isoformat(),))
        rt.store.conn.commit()
        u = usage_today(rt.store.conn, NOW)
    finally:
        rt.close()
    assert (u.runs, u.model_calls) == (2, 6) and round(u.usd, 2) == 0.02


def test_clip_lowers_the_run_budget_to_what_is_left():
    _prior_run(4)
    guard = UnattendedGuard(DailyCap(max_model_calls=5, max_notional_usd=1.0))
    rt = open_runtime()
    try:
        assert guard.clip({"max_model_calls": 12}, rt.store.conn, NOW) == (1, 0.96)
        assert guard.clip({}, rt.store.conn, NOW)[0] == 1
    finally:
        rt.close()


# ---------------------------------------------------------------- daily cap in the scheduler


def test_cap_blocks_unattended_runs_notifies_once_and_never_blocks_run_now():
    note = FakeNotifier()
    chats = ScriptedChats(["Summary for Sachin."])
    p = proactive(NOW, chats, note, unattended=CAP)
    s = p.save(_draft())
    _prior_run(3)
    runner = p.runner()
    r1 = runner.run(s.id, "cron")
    assert r1.status == "capped" and chats.calls == 0
    assert sum("Daily cap" in text for _, text in note.sent) == 1
    assert runner.run(s.id, "cron").status == "capped"
    assert sum("Daily cap" in text for _, text in note.sent) == 1   # only one notice a day
    assert runner.run(s.id, "run-now").status == "ok"                # Sachin asked himself
    rt = open_runtime()
    try:
        runs = ScheduleStore(rt.store.conn).runs(s.id)
    finally:
        rt.close()
    assert [r["status"] for r in runs] == ["ok", "capped", "capped"]


def test_next_day_the_cap_resets():
    note = FakeNotifier()
    p = proactive(NOW, ScriptedChats(["fresh day"]), note, unattended=CAP)
    s = p.save(_draft())
    _prior_run(3)
    p.clock.now = NOW + timedelta(hours=12)          # 09:00 next day
    assert p.runner().run(s.id, "cron").status == "ok"


def test_cap_notice_text_says_how_to_change_it():
    assert "config/local.yaml" in cap_notice("200 model calls today (cap 200)")


# ---------------------------------------------------------------- runaway guard


def _failing_runner(note, clock, fails):
    calls = iter(fails)

    def executor(ctx):
        if next(calls):
            raise RuntimeError("tool kept timing out")
        return "fine"

    guard = UnattendedGuard(DailyCap(), pause_after_failures=3)
    return ScheduleRunner(open_runtime, {"prompt": executor}, note, clock, guard=guard)


def _add_schedule(clock):
    rt = open_runtime()
    try:
        return ScheduleStore(rt.store.conn).add(_draft("flaky job"), clock(), 3600)
    finally:
        rt.close()


def test_three_failures_in_a_row_pause_the_schedule_and_tell_sachin():
    note, clock = FakeNotifier(), Clock(NOW)
    s = _add_schedule(clock)
    runner = _failing_runner(note, clock, [True, True, True])
    assert [runner.run(s.id, "cron").status for _ in range(3)] == ["failed", "failed", "failed"]
    rt = open_runtime()
    try:
        assert ScheduleStore(rt.store.conn).get(s.id).enabled is False
    finally:
        rt.close()
    assert any("Paused schedule flaky job" in text for _, text in note.sent)
    assert runner.run(s.id, "cron").status == "paused"


def test_a_success_resets_the_failure_streak():
    note, clock = FakeNotifier(), Clock(NOW)
    s = _add_schedule(clock)
    runner = _failing_runner(note, clock, [True, True, False, True, True])
    statuses = [runner.run(s.id, "cron").status for _ in range(5)]
    assert statuses == ["failed", "failed", "ok", "failed", "failed"]
    rt = open_runtime()
    try:
        assert ScheduleStore(rt.store.conn).get(s.id).enabled is True
    finally:
        rt.close()


# ---------------------------------------------------------------- daily cap in triggers


def test_trigger_action_is_capped_but_plain_notifications_still_go_out(isolated):
    inbox = isolated / "workspace" / "inbox"
    inbox.mkdir(parents=True)
    note = FakeNotifier()
    chats = ScriptedChats(["should not run"])
    p = proactive(NOW, chats, note, triggers=TRIG, unattended=CAP)
    p.clock = Clock(NOW)
    p.extras.update(web=FakeWeb(), tavily_key=lambda: "tvly-test", google_client=lambda: None,
                    connectors_cfg={"gmail": {"header_class": "P2"}, "google": {"calendar_id": "primary"}})
    summarize = p.save_trigger(p.draft_trigger("when a new file arrives in workspace/inbox summarize it", {}))
    tell = p.save_trigger(p.draft_trigger("when a new file arrives in workspace/inbox tell me", {}))
    engine = p.trigger_engine()
    engine.poll(summarize.id), engine.poll(tell.id)            # baselines
    _prior_run(3)
    (inbox / "report.txt").write_text("new report", encoding="utf-8")
    p.clock.now = NOW + timedelta(minutes=5)
    capped = p.trigger_engine().poll(summarize.id)
    plain = p.trigger_engine().poll(tell.id)
    assert capped.fire_status == "capped" and chats.calls == 0
    assert "daily cap" in capped.text.lower()
    assert plain.fire_status == "ok"


# ---------------------------------------------------------------- memory conflicts


def _mem(name, subject, body, mtype="fact", status="active", valid_from="2026-10-01"):
    return Memory(name=name, type=mtype, body=body, subject=subject, status=status, valid_from=valid_from,
                  evidence='"example"')


def test_find_conflicts_only_same_subject_same_type_and_different_bodies():
    a = _mem("Car colour", "car", "The car is red.")
    b = _mem("Car colour new", "car", "The car is blue.")
    c = _mem("Car colour copy", "car", "the car is RED.")           # same text as a
    d = _mem("Old car", "car", "The car is green.", status="superseded")
    e = _mem("Bike", "bike", "The bike is black.")
    f = _mem("Car preference", "car", "Likes red cars.", mtype="preference")
    for i, m in enumerate([a, b, c, d, e, f]):
        m.id = f"m-{i:04d}"
    found = find_conflicts([a, b, c, d, e, f])
    assert len(found) == 1 and found[0].subject == "car" and found[0].type == "fact"
    assert {m.id for m in found[0].memories} == {"m-0000", "m-0001", "m-0002"}


def test_memory_conflicts_cli_and_brief_section():
    rt = open_runtime()
    try:
        rt.memory.save(_mem("Office floor", "office", "The office is on floor 3."))
        rt.memory.save(_mem("Office floor update", "office", "The office is on floor 5."))
        ctx = BriefContext(now=NOW, home=rt.paths.home, store=rt.store, settings=None)
        assert "1 possible memory conflict" in MemoryConflictsSection().render(ctx)
    finally:
        rt.close()
    out = io.StringIO()
    assert cli_main(["memory", "conflicts"], out=out) == 0
    text = out.getvalue()
    assert "office" in text and "floor 3" in text and "floor 5" in text


def test_brief_section_is_silent_without_conflicts():
    rt = open_runtime()
    try:
        ctx = BriefContext(now=NOW, home=rt.paths.home, store=rt.store, settings=None)
        assert MemoryConflictsSection().render(ctx) is None
    finally:
        rt.close()


# ---------------------------------------------------------------- nightly review


def test_nightly_review_writes_the_episode_and_keeps_sachins_notes():
    rt = open_runtime()
    try:
        rt.memory.save(_mem("Garden watering", "garden", "Water the garden at 7.", valid_from="2026-10-12"))
        rt.memory.save(_mem("Office floor", "office", "Floor 3."))
        rt.memory.save(_mem("Office floor update", "office", "Floor 5."))
        rt.store.conn.execute("INSERT INTO tasks (id, title, state, updated_at) VALUES "
                              "('t-001', 'Compare example laptops', 'COMPLETED', '2026-10-12 10:00:00')")
        rt.store.conn.commit()
        _prior_run(2)
        result = nightly_review(rt.paths.home, rt.store.conn, rt.memory, NOW)
        path = episode_path(rt.paths.home, NOW.date())
        assert result.path == path and path.exists() and result.conflicts == 1
        text = path.read_text(encoding="utf-8")
        assert "Compare example laptops" in text and "Garden watering" in text and "office (fact)" in text
        assert "1 task(s)" in result.summary and "Compare example" not in result.summary   # output: counts only
        path.write_text(text + "\nMy own note: call the plumber.\n", encoding="utf-8")
        nightly_review(rt.paths.home, rt.store.conn, rt.memory, NOW + timedelta(minutes=30))
        again = path.read_text(encoding="utf-8")
        assert again.count("## Nightly review") == 1 and "call the plumber" in again
        assert rt.memory.reindex() == 3                  # the episode file does not disturb the memory index
    finally:
        rt.close()


def test_default_review_schedule_runs_through_the_scheduler():
    p = proactive(NOW, ScriptedChats(), FakeNotifier())
    p.ensure_default_schedules()
    rt = open_runtime()
    try:
        review = next(s for s in ScheduleStore(rt.store.conn).list() if s.kind == "review")
    finally:
        rt.close()
    assert review.cron == "30 22 * * *" and review.output == "file"
    result = p.runner().run(review.id, "cron")
    assert result.status == "ok" and "Nightly review saved" in result.text
