"""Missed-run alerts: one grouped notice for runs missed while the computer was asleep or off;
frequent checks (heartbeat, memory extraction) stay quiet. Offline, synthetic schedules."""

from types import SimpleNamespace

from jarvis.core.runtime import open_runtime
from jarvis.proactive.schedule_parse import ScheduleDraft
from jarvis.proactive.scheduler import ScheduleStore

from test_proactive_support import FakeNotifier, ScriptedChats, at, proactive


def _draft(name, kind="prompt", cron="0 9 * * *"):
    return ScheduleDraft(name=name, kind=kind, input=name if kind == "prompt" else "", cron=cron,
                         timezone="Asia/Kolkata", description="test", output="telegram")


def _missed_setup(note, **over):
    p = proactive(at(2026, 10, 10, 15, 0), ScriptedChats(), note, **over)
    report = p.save(_draft("weekly report", cron="0 9 * * mon"))
    beat = p.save(_draft("heartbeat", kind="heartbeat", cron="*/30 * * * *"))
    p.clock.now = at(2026, 10, 12, 13, 0)          # Monday 13:00: the 09:00 report is 4 h late (grace 1 h)
    return p, report, beat


def test_catch_up_sends_one_grouped_notice_and_skips_frequent_checks():
    note = FakeNotifier()
    p, report, beat = _missed_setup(note)
    rt = open_runtime()
    try:
        ScheduleStore(rt.store.conn).set_next(beat.id, at(2026, 10, 12, 9, 0))
    finally:
        rt.close()
    p.service().catch_up()
    notices = [t for _, t in note.sent if t.startswith("Missed while Jarvis was off")]
    assert len(notices) == 1
    assert "weekly report" in notices[0] and report.id in notices[0] and "Mon 12 Oct 09:00" in notices[0]
    assert "heartbeat" not in notices[0]


def test_alerts_can_be_switched_off():
    note = FakeNotifier()
    p, *_ = _missed_setup(note, schedules={"misfire_grace_minutes": 60, "default_output": "telegram",
                                           "default_budget": {"max_model_calls": 12}, "alert_missed": False})
    p.service().catch_up()
    assert not any(t.startswith("Missed while") for _, t in note.sent)


def test_nothing_missed_means_no_notice():
    note = FakeNotifier()
    p = proactive(at(2026, 10, 10, 15, 0), ScriptedChats(), note)
    p.save(_draft("weekly report", cron="0 9 * * mon"))
    p.service().catch_up()
    assert note.sent == []


def test_apscheduler_missed_event_alerts_for_normal_schedules_only():
    from apscheduler.events import EVENT_JOB_MISSED

    note = FakeNotifier()
    p, report, beat = _missed_setup(note)
    svc = p.service()
    svc._on_event(SimpleNamespace(code=EVENT_JOB_MISSED, job_id=beat.id, scheduled_run_time="2026-10-12T09:00:00+05:30"))
    assert note.sent == []
    svc._on_event(SimpleNamespace(code=EVENT_JOB_MISSED, job_id=report.id, scheduled_run_time="2026-10-12T09:00:00+05:30"))
    assert len(note.sent) == 1 and "weekly report" in note.sent[0][1]
