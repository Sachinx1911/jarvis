"""Schedules: missed runs, coalescing, overlap, unattended safety, budget, stop, outputs, APScheduler jobs."""

import json
from datetime import timedelta
from pathlib import Path

import pytest

from jarvis.control.stop import StopSwitch
from jarvis.core.runtime import open_runtime
from jarvis.proactive.schedule_parse import ScheduleDraft
from jarvis.proactive.scheduler import (
    PendingApprovals, ScheduleRunner, ScheduleService, ScheduleStore, missed_run_action,
)

from test_proactive_support import FakeNotifier, ScriptedChats, at, proactive


def _draft(cron="0 9 * * mon", kind="prompt", input="project summary", output="telegram", target="", budget=None):
    return ScheduleDraft(name=input[:40] or kind, kind=kind, input=input, cron=cron, timezone="Asia/Kolkata",
                         description="test", target=target, output=output, budget=budget or {})


def _store():
    rt = open_runtime()
    return rt, ScheduleStore(rt.store.conn)


def _schedule(p, **kw):
    return p.save(_draft(**kw))


def _get(sid):
    rt, store = _store()
    try:
        return store.get(sid), store.runs(sid)
    finally:
        rt.close()


def _set_next(sid, when):
    rt, store = _store()
    store.set_next(sid, when)
    rt.close()


# ---- missed runs (PLAN 10.3: run once on wake if within grace, else skip) ----

def test_missed_run_action():
    due = at(2026, 10, 12, 9, 0)
    grace = timedelta(minutes=60)
    assert missed_run_action(due, at(2026, 10, 12, 8, 59), grace) is None
    assert missed_run_action(due, at(2026, 10, 12, 9, 30), grace) == "run"
    assert missed_run_action(due, at(2026, 10, 12, 10, 0), grace) == "run"
    assert missed_run_action(due, at(2026, 10, 12, 10, 1), grace) == "skip"


def test_weekly_schedule_missed_within_grace_runs_once_on_wake():
    chats = ScriptedChats(["Here is the project summary."])
    note = FakeNotifier()
    p = proactive(at(2026, 10, 10, 15, 0), chats, note)           # Saturday: created
    s = _schedule(p)
    assert s.next_run_at == "2026-10-12T09:00:00+05:30"
    p.clock.now = at(2026, 10, 12, 9, 40)                          # laptop woke 40 min late on Monday
    results = p.service().catch_up()
    assert [r.status for r in results] == ["ok"]
    s, runs = _get(s.id)
    assert runs[0]["trigger"] == "catch-up" and runs[0]["status"] == "ok"
    assert s.next_run_at == "2026-10-19T09:00:00+05:30"            # next week, not a second run now
    assert note.sent and "project summary" in note.sent[0][1].lower()


def test_weekly_schedule_missed_past_grace_is_skipped_and_recorded():
    chats = ScriptedChats(["should not run"])
    p = proactive(at(2026, 10, 10, 15, 0), chats)
    s = _schedule(p)
    p.clock.now = at(2026, 10, 12, 13, 0)                          # 4 hours late, grace is 1 hour
    assert p.service().catch_up() == []
    s, runs = _get(s.id)
    assert runs[0]["status"] == "missed" and runs[0]["trigger"] == "catch-up"
    assert s.last_status == "missed"
    assert s.next_run_at == "2026-10-19T09:00:00+05:30"
    assert chats.calls == 0


def test_many_missed_runs_coalesce_into_one():
    chats = ScriptedChats(["one"], ["two"], ["three"])
    p = proactive(at(2026, 10, 10, 15, 0), chats)
    s = p.save(_draft(cron="0 * * * *"))
    rt, store = _store()
    store.db.execute("UPDATE sched_schedules SET misfire_grace_s=? WHERE id=?", (4 * 3600, s.id))
    store.db.commit()
    rt.close()
    _set_next(s.id, at(2026, 10, 10, 16, 0))
    p.clock.now = at(2026, 10, 10, 18, 30)                         # 16:00, 17:00, 18:00 all missed
    assert len(p.service().catch_up()) == 1
    assert chats.calls == 1
    _, runs = _get(s.id)
    assert len(runs) == 1


# ---- overlap ----

def test_overlap_is_prevented():
    chats = ScriptedChats(["should not run"])
    p = proactive(at(2026, 10, 12, 9, 0), chats)
    s = _schedule(p)
    rt, store = _store()
    assert store.acquire(s.id, at(2026, 10, 12, 8, 59), timedelta(hours=6))   # a run is going
    rt.close()
    result = p.runner().run(s.id, "cron")
    assert result.status == "skipped_overlap"
    assert chats.calls == 0
    _, runs = _get(s.id)
    assert runs[0]["status"] == "skipped_overlap"


def test_stale_lock_from_a_crash_is_taken_over():
    chats = ScriptedChats(["done"])
    p = proactive(at(2026, 10, 12, 9, 0), chats)
    s = _schedule(p)
    rt, store = _store()
    assert store.acquire(s.id, at(2026, 10, 12, 1, 0), timedelta(hours=6))    # 8 hours ago
    rt.close()
    assert p.runner().run(s.id, "cron").status == "ok"
    s, _ = _get(s.id)
    assert s.running_since is None                                            # lock released


def test_apscheduler_jobs_have_missed_run_and_overlap_settings():
    p = proactive(at(2026, 10, 10, 15, 0))
    s = _schedule(p)
    svc = p.service()
    svc.start()
    try:
        job = svc.scheduler.get_job(s.id)
        assert job.max_instances == 1 and job.coalesce is True and job.misfire_grace_time == 3600
        assert svc.scheduler.get_job("_reminders") is not None
        rt, store = _store()
        store.set_enabled(s.id, False, p.now())                               # paused from the CLI
        rt.close()
        svc.sync()
        assert svc.scheduler.get_job(s.id) is None
        rt, store = _store()
        store.set_enabled(s.id, True, p.now())
        rt.close()
        svc.sync()
        assert svc.scheduler.get_job(s.id) is not None
    finally:
        svc.shutdown()


def test_apscheduler_missed_event_is_recorded():
    from types import SimpleNamespace

    from apscheduler.events import EVENT_JOB_MISSED

    p = proactive(at(2026, 10, 10, 15, 0))
    s = _schedule(p)
    svc = p.service()
    svc._on_event(SimpleNamespace(job_id=s.id, code=EVENT_JOB_MISSED, scheduled_run_time="2026-10-12 09:00"))
    _, runs = _get(s.id)
    assert runs[0]["status"] == "missed"


# ---- unattended runs never do T2+ ----

def test_unattended_run_never_executes_t2_or_t3(isolated):
    ws = isolated / "workspace"
    ws.mkdir(exist_ok=True)
    (ws / "notes.txt").write_text("original", encoding="utf-8")
    chats = ScriptedChats([
        {"tool": "overwrite_file", "arguments": {"path": "notes.txt", "content": "changed"}},
        {"tool": "delete_file", "arguments": {"path": "notes.txt"}},
        {"tool": "write_file", "arguments": {"path": "report.md", "content": "weekly report"}},
        "Done what I could.",
    ])
    note = FakeNotifier()
    p = proactive(at(2026, 10, 12, 9, 0), chats, note)
    s = _schedule(p)
    result = p.runner().run(s.id, "cron")
    assert result.status == "ok"
    assert (ws / "notes.txt").read_text(encoding="utf-8") == "original"      # T2 and T3 did not run
    assert (ws / "report.md").read_text(encoding="utf-8") == "weekly report"  # T1 did
    assert result.pending == 2
    rt = open_runtime()
    pending = PendingApprovals(rt.store.conn).list()
    decisions = [r[0] for r in rt.store.conn.execute("SELECT decision FROM approvals ORDER BY id")]
    rt.close()
    assert [(a["tool"], a["tier"], a["schedule_id"]) for a in pending] == [
        ("overwrite_file", "T2", s.id), ("delete_file", "T3", s.id)]
    assert pending[0]["arguments"] == {"path": "notes.txt", "content": "changed"}
    assert decisions == ["denied", "denied"]
    assert "need your approval" in note.sent[0][1]
    # The run receipt names each refused action (tool and tier only; arguments stay in the queue).
    assert "- #1 overwrite_file (T2): refused unattended, waiting for approval" in note.sent[0][1]
    assert "- #2 delete_file (T3): refused unattended, waiting for approval" in note.sent[0][1]
    assert "changed" not in note.sent[0][1].split("need your approval")[1]
    _, runs = _get(s.id)
    assert "overwrite_file (T2)" in runs[0]["detail"] and "delete_file (T3)" in runs[0]["detail"]
    assert "Sachin is not watching" in chats.providers[0].requests[0].messages[-1].text_content()


def test_t4_never_runs_unattended(isolated):
    chats = ScriptedChats([{"tool": "read_file", "arguments": {"path": "../.env"}}, "ok"])
    p = proactive(at(2026, 10, 12, 9, 0), chats)
    s = _schedule(p)
    assert p.runner().run(s.id, "cron").status == "ok"
    rt = open_runtime()
    rows = rt.store.conn.execute("SELECT tool, ok FROM tool_runs").fetchall()
    rt.close()
    assert all(not ok for _, ok in rows)


# ---- stop, budget, pause, outputs, kinds ----

def test_emergency_stop_blocks_scheduled_runs(isolated):
    chats = ScriptedChats(["should not run"])
    p = proactive(at(2026, 10, 12, 9, 0), chats)
    s = _schedule(p)
    StopSwitch(isolated / "data").engage("test")
    assert p.runner().run(s.id, "cron").status == "stopped"
    assert chats.calls == 0


def test_budget_stops_a_run():
    chats = ScriptedChats([{"tool": "list_folder", "arguments": {"path": ""}}, "never reached"])
    p = proactive(at(2026, 10, 12, 9, 0), chats)
    s = p.save(_draft(budget={"max_model_calls": 1}))
    result = p.runner().run(s.id, "cron")
    assert result.status == "budget"
    assert chats.calls == 2  # the second call is the one that went over; nothing after it


def test_paused_schedule_does_not_fire_but_run_now_works():
    chats = ScriptedChats(["manual run"])
    p = proactive(at(2026, 10, 12, 9, 0), chats)
    s = _schedule(p)
    rt, store = _store()
    store.set_enabled(s.id, False, p.now())
    rt.close()
    assert p.runner().run(s.id, "cron").status == "paused"
    assert chats.calls == 0
    assert p.runner().run(s.id, "run-now").status == "ok"


def test_file_output_is_written(isolated):
    p = proactive(at(2026, 10, 12, 9, 0), ScriptedChats(["Report body"]), FakeNotifier())
    s = p.save(_draft(output="file"))
    result = p.runner().run(s.id, "cron")
    path = Path(result.output_path)
    assert path.parent == isolated / "data" / "schedules" / s.id
    assert "Report body" in path.read_text(encoding="utf-8")
    assert p.notifier.sent == []  # file only


def test_failing_run_is_recorded_and_lock_released():
    def boom(rt, approver):
        raise RuntimeError("provider exploded")
    p = proactive(at(2026, 10, 12, 9, 0))
    p.chat_factory = boom
    s = _schedule(p)
    assert p.runner().run(s.id, "cron").status == "failed"
    s, runs = _get(s.id)
    assert s.running_since is None and runs[0]["status"] == "failed" and "provider exploded" in runs[0]["detail"]


def test_agent_schedule_runs_a_team_task_unattended(monkeypatch):
    from jarvis.proactive import integration

    ran = []

    class FakeRunner:
        def __init__(self, rt):
            self.rt = rt

        def run(self, task_id):
            ran.append(task_id)
            from jarvis.core.runtime import task_store
            return task_store(self.rt).get(task_id)

    monkeypatch.setattr(integration, "RUNNER_FACTORY", FakeRunner)
    p = proactive(at(2026, 10, 12, 9, 0))
    s = p.save(_draft(kind="agent", target="writer", input="Write the weekly project summary"))
    result = p.runner().run(s.id, "cron")
    assert result.status == "ok" and "t-001" in result.text and ran == ["t-001"]
    rt = open_runtime()
    row = rt.store.conn.execute("SELECT goal, owner FROM tasks").fetchone()
    rt.close()
    assert row == ("Write the weekly project summary", "writer")


def test_skill_and_agent_need_a_target():
    p = proactive(at(2026, 10, 12, 9, 0))
    with pytest.raises(ValueError):
        p.save(_draft(kind="skill", target=""))


def test_brief_schedule_runs_without_a_model():
    note = FakeNotifier()
    chats = ScriptedChats()
    p = proactive(at(2026, 10, 12, 8, 0), chats, note)
    s = p.save(_draft(kind="brief", input="", cron="0 8 * * *"))
    assert p.runner().run(s.id, "cron").status == "ok"
    assert "Good morning, sir." in note.sent[0][1]
    assert chats.calls == 0


def test_default_schedules_created_once_and_deletion_is_respected():
    p = proactive(at(2026, 10, 10, 15, 0))
    added = p.ensure_default_schedules()
    assert len(added) == 4
    rt, store = _store()
    kinds = {s.kind: s for s in store.list()}
    assert kinds["brief"].cron == "0 8 * * *" and kinds["heartbeat"].cron == "*/30 * * * *"
    assert kinds["heartbeat"].misfire_grace_s == 300
    assert kinds["memory_extract"].cron == "*/10 * * * *" and kinds["memory_extract"].output == "file"
    assert kinds["memory_cleanup"].cron == "0 21 * * sun"
    store.delete(kinds["heartbeat"].id)
    rt.close()
    assert p.ensure_default_schedules() == []          # Sachin deleted it: stays deleted


def test_run_receipt_has_usage():
    p = proactive(at(2026, 10, 12, 9, 0), ScriptedChats(["summary"]))
    s = _schedule(p)
    p.runner().run(s.id, "cron")
    _, runs = _get(s.id)
    assert runs[0]["model_calls"] == 1 and runs[0]["finished_at"]


def test_pending_approval_can_be_dismissed():
    p = proactive(at(2026, 10, 12, 9, 0), ScriptedChats([
        {"tool": "open_url", "arguments": {"url": "https://example.com"}}, "ok"]))
    s = _schedule(p)
    p.runner().run(s.id, "cron")
    rt = open_runtime()
    pending = PendingApprovals(rt.store.conn)
    [item] = pending.list()
    assert pending.dismiss(item["id"]) and pending.list() == []
    rt.close()
    assert json.dumps(item["arguments"]) == '{"url": "https://example.com"}'
