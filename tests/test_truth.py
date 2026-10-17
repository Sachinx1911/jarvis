"""File truth (PLAN.md 27.1 law 2, 27.12): write-through for tasks, schedules and triggers; the
pralaya test (delete the database, rebuild from files, same system); verify reports tampering and
rebuild lets the file win; prune writes an orphan row out first; task archive (finished tasks only).
Offline: no model, no network."""

from __future__ import annotations

import io
import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from jarvis.cli import main as cli_main
from jarvis.core import truth
from jarvis.core.rebuild import rebuild, verify
from jarvis.db import Store
from jarvis.proactive.schedule_parse import ScheduleDraft
from jarvis.proactive.scheduler import ScheduleStore
from jarvis.proactive.trigger_parse import TriggerDraft
from jarvis.proactive.triggers import TriggerStore
from jarvis.tasks.store import TaskStore, TransitionError

from test_web_api_app import cfgdir  # noqa: F401 - the dashboard fixture

NOW =datetime(2026, 10, 17, 9, 0, tzinfo=ZoneInfo("Asia/Kolkata"))


def _open(home):
    return Store(home / "data" / "jarvis.db")


def _stores(home, store):
    return (TaskStore(store, home / "data" / "tasks"), ScheduleStore(store.conn), TriggerStore(store.conn))


def _schedule_draft(name="project summary", cron="0 9 * * mon", workspace="personal"):
    return ScheduleDraft(name=name, kind="prompt", input="summarise the example project", cron=cron,
                         timezone="Asia/Kolkata", description="test", output="file", budget={"max_model_calls": 3},
                         workspace=workspace)


def _trigger_draft(home, name="watch inbox folder"):
    folder = home / "workspace" / "inbox"
    folder.mkdir(parents=True, exist_ok=True)
    return TriggerDraft(name, "file_new", {"folder": str(folder), "glob": "*.md"}, action="notify",
                        description="new file in the inbox folder")


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- write-through


def test_task_changes_are_written_through_to_its_file(isolated):
    store = _open(isolated)
    ts, _, _ = _stores(isolated, store)
    t = ts.create("Compare three example laptops", project="laptop", priority=1, workspace="personal")
    path = truth.truth_path(isolated, "tasks", t.id)
    assert path == isolated / "data" / "tasks" / t.id / "task.json"
    rec = _read(path)
    assert rec["id"] == t.id and rec["state"] == "BACKLOG" and rec["priority"] == 1 and rec["project"] == "laptop"
    assert rec["truth_version"] == truth.TRUTH_VERSION and rec["archived_at"] is None

    ts.update(t.id, plan={"mode": "team", "steps": ["a", "b"]}, current_step="a")
    rec = _read(path)
    assert rec["plan"] == {"mode": "team", "steps": ["a", "b"]} and rec["current_step"] == "a"

    ts.set_state(t.id, "CANCELLED", "no longer needed")
    assert _read(path)["state"] == "CANCELLED"

    events = truth.read_events(isolated, t.id)
    assert [e["kind"] for e in events] == ["created", "state"]
    assert json.loads(events[1]["detail"])["to"] == "CANCELLED"
    assert [e["kind"] for e in ts.events(t.id)] == ["created", "state"]
    # canonical form: sorted keys, indent 2, non-ASCII kept
    text = path.read_text(encoding="utf-8")
    assert text.startswith('{\n  "archived_at"') and text.endswith("}\n")
    store.close()


def test_schedule_changes_are_written_through_to_its_file(isolated):
    store = _open(isolated)
    _, ss, _ = _stores(isolated, store)
    s = ss.add(_schedule_draft(), NOW, 3600, source="cli")
    path = truth.truth_path(isolated, "schedules", s.id)
    assert path == isolated / "data" / "schedules" / f"{s.id}.json"
    rec = _read(path)
    assert rec["cron"] == "0 9 * * mon" and rec["enabled"] is True and rec["budget"] == {"max_model_calls": 3}
    assert "running_since" not in rec   # the overlap lock is not truth

    ss.set_enabled(s.id, False, NOW)
    assert _read(path)["enabled"] is False and _read(path)["next_run_at"] is None
    assert ss.archive(s.id, NOW)
    assert _read(path)["archived_at"] == NOW.isoformat(timespec="seconds")
    assert ss.unarchive(s.id, NOW)
    assert _read(path)["archived_at"] is None
    run_id = ss.start_run(s.id, "run-now", NOW)
    ss.finish_run(run_id, s.id, "ok", "done", NOW)
    assert _read(path)["last_status"] == "ok"
    store.close()


def test_trigger_changes_are_written_through_to_its_file(isolated):
    store = _open(isolated)
    _, _, tr = _stores(isolated, store)
    t = tr.add(_trigger_draft(isolated), NOW, created_by="cli", workspace="personal")
    path = truth.truth_path(isolated, "triggers", t.id)
    assert path == isolated / "data" / "triggers" / f"{t.id}.json"
    rec = _read(path)
    assert rec["source"] == "file_new" and rec["condition"]["glob"] == "*.md" and rec["enabled"] is True

    tr.update_poll(t.id, NOW, "baseline", "3 noted", NOW, failures=0, state={"baseline": True})
    rec = _read(path)
    assert rec["state"] == {"baseline": True} and rec["last_status"] == "baseline"
    tr.set_enabled(t.id, False, NOW)
    assert _read(path)["enabled"] is False
    assert tr.archive(t.id, NOW)
    assert _read(path)["archived_at"]
    store.close()


def test_delete_forever_is_the_only_thing_that_removes_a_truth_file(isolated):
    store = _open(isolated)
    _, ss, tr = _stores(isolated, store)
    s = ss.add(_schedule_draft(), NOW, 3600)
    t = tr.add(_trigger_draft(isolated), NOW)
    s_path, t_path = truth.truth_path(isolated, "schedules", s.id), truth.truth_path(isolated, "triggers", t.id)
    assert not ss.delete_forever(s.id) and s_path.exists()   # a live one is never deleted
    ss.archive(s.id, NOW)
    tr.archive(t.id, NOW)
    assert ss.delete_forever(s.id) and not s_path.exists()
    assert tr.delete_forever(t.id) and not t_path.exists()
    assert verify(isolated, store).ok
    store.close()


def test_an_in_memory_database_has_no_file_truth(isolated):
    import sqlite3

    conn = sqlite3.connect(":memory:")
    ss = ScheduleStore(conn)
    assert ss.home is None
    s = ss.add(_schedule_draft(), NOW, 3600)
    assert ss.get(s.id) and not (isolated / "data" / "schedules").exists()


# ---------------------------------------------------------------- the pralaya test


def _world(home):
    """A small world: two tasks (one archived), two schedules (one paused, one archived), two triggers."""
    store = _open(home)
    ts, ss, tr = _stores(home, store)
    t1 = ts.create("Compare three example laptops", project="laptop", priority=1, workspace="personal")
    ts.update(t1.id, owner="researcher", plan={"mode": "team"}, checkpoint={"step": 2})
    ts.event(t1.id, "note", {"text": "देवनागरी ठीक आहे"})
    t2 = ts.create("Draft the example newsletter", workspace="personal")
    ts.set_state(t2.id, "CANCELLED", "dropped")
    ts.archive(t2.id, NOW)
    s1 = ss.add(_schedule_draft("weekly summary", "0 9 * * mon"), NOW, 3600, source="cli")
    s2 = ss.add(_schedule_draft("daily check", "15 7 * * *"), NOW, 1800, source="telegram")
    ss.set_enabled(s2.id, False, NOW)
    ss.archive(s2.id, NOW)
    r1 = tr.add(_trigger_draft(home, "inbox"), NOW, created_by="cli")
    tr.update_poll(r1.id, NOW, "baseline", "2 noted", NOW, failures=0, state={"baseline": True})
    r2 = tr.add(_trigger_draft(home, "drafts"), NOW, created_by="telegram", workspace="personal")
    tr.set_enabled(r2.id, False, NOW)
    run = ss.start_run(s1.id, "run-now", NOW)
    ss.finish_run(run, s1.id, "ok", "fine", NOW)
    return store, (t1.id, t2.id), (s1.id, s2.id), (r1.id, r2.id)


def _snapshot(home, store):
    ts, ss, tr = _stores(home, store)
    tasks = {t.id: (t.state, t.workspace, t.owner, t.plan, t.checkpoint, t.priority, t.project, t.archived_at,
                    t.created_at, t.updated_at) for t in ts.list(include_final=True, include_archived=True)}
    events = {tid: [(e["ts"], e["kind"], e["detail"]) for e in ts.events(tid)] for tid in tasks}
    sched = {s.id: (s.cron, s.enabled, s.workspace, s.archived_at, s.name, s.budget, s.source, s.last_status,
                    s.next_run_at, s.misfire_grace_s) for s in ss.list(include_archived=True)}
    trig = {t.id: (t.source, t.condition, t.enabled, t.workspace, t.archived_at, t.state, t.created_by,
                   t.last_status, t.failures) for t in tr.list(include_archived=True)}
    return tasks, events, sched, trig


def _pralaya(home):
    for name in ("jarvis.db", "jarvis.db-wal", "jarvis.db-shm", "jarvis.db-journal"):
        path = home / "data" / name
        if path.exists():
            os.remove(path)


def test_pralaya_delete_the_database_rebuild_and_the_world_is_the_same(isolated):
    store, task_ids, sched_ids, trig_ids = _world(isolated)
    before = _snapshot(isolated, store)
    assert verify(isolated, store).ok
    store.close()

    _pralaya(isolated)
    assert not (isolated / "data" / "jarvis.db").exists()

    fresh = _open(isolated)
    ts, ss, tr = _stores(isolated, fresh)
    assert ts.list(include_final=True, include_archived=True) == [] and ss.list(include_archived=True) == []
    report = rebuild(isolated, fresh)
    assert sorted(report.created) == sorted([("tasks", i) for i in task_ids] + [("schedules", i) for i in sched_ids]
                                            + [("triggers", i) for i in trig_ids])
    assert report.events_restored == len(before[1][task_ids[0]]) + len(before[1][task_ids[1]])
    assert report.ok and report.updated == [] and report.rows_without_files == []
    after = _snapshot(isolated, fresh)
    assert after == before
    assert ts.get(task_ids[1]).archived_at == NOW.isoformat(timespec="seconds")
    assert ss.get(sched_ids[1]).archived and not ss.get(sched_ids[1]).enabled
    assert tr.get(trig_ids[0]).state == {"baseline": True}
    assert verify(isolated, fresh).ok
    assert "ok" in rebuild(isolated, fresh).lines()[-1]   # a second rebuild changes nothing
    # the next id continues after the rebuilt ones: names are given once, for ever (27.12)
    assert ts.create("one more").id == "t-003" and ss.add(_schedule_draft("x"), NOW, 60).id == "s-003"
    fresh.close()


def test_rebuild_is_the_same_whether_run_through_the_cli_or_not(isolated):
    store, task_ids, sched_ids, trig_ids = _world(isolated)
    before = _snapshot(isolated, store)
    store.close()
    _pralaya(isolated)
    out = io.StringIO()
    assert cli_main(["rebuild"], out=out) == 0
    text = out.getvalue()
    assert f"created tasks {task_ids[0]} from its file" in text and "ok" in text.splitlines()[-1]
    fresh = _open(isolated)
    assert _snapshot(isolated, fresh) == before
    fresh.close()
    audit = (isolated / "data" / "audit.jsonl").read_text(encoding="utf-8")
    assert '"event": "truth_rebuilt"' in audit and '"created": 6' in audit
    out = io.StringIO()
    assert cli_main(["verify"], out=out) == 0 and out.getvalue().splitlines()[-1] == "ok"
    assert '"event": "truth_verified"' in (isolated / "data" / "audit.jsonl").read_text(encoding="utf-8")


# ---------------------------------------------------------------- verify: differences, tampering, prune


def test_verify_reports_a_tampered_file_and_rebuild_lets_the_file_win(isolated):
    store, task_ids, sched_ids, trig_ids = _world(isolated)
    s_path = truth.truth_path(isolated, "schedules", sched_ids[0])
    rec = _read(s_path)
    rec["cron"] = "30 10 * * fri"
    rec["workspace"] = "acme"
    s_path.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
    t_path = truth.truth_path(isolated, "tasks", task_ids[0])
    rec = _read(t_path)
    rec["priority"] = 3
    t_path.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")

    report = verify(isolated, store)
    assert not report.ok
    assert {(d.kind, d.id) for d in report.differing} == {("schedules", sched_ids[0]), ("tasks", task_ids[0])}
    sched_diff = next(d for d in report.differing if d.kind == "schedules")
    assert sched_diff.fields == {"cron": ("30 10 * * fri", "0 9 * * mon"), "workspace": ("acme", "personal")}
    assert any("cron: file='30 10 * * fri' row='0 9 * * mon'" in line for line in report.lines())
    out = io.StringIO()
    assert cli_main(["verify"], out=out) == 1 and "not ok" in out.getvalue()

    dry = rebuild(isolated, store, dry_run=True)
    assert len(dry.updated) == 2 and verify(isolated, store).differing   # a dry run changes nothing

    report = rebuild(isolated, store)
    assert {(d.kind, d.id) for d in report.updated} == {("schedules", sched_ids[0]), ("tasks", task_ids[0])}
    _, ss, _ = _stores(isolated, store)
    s = ss.get(sched_ids[0])
    assert s.cron == "30 10 * * fri" and s.workspace == "acme"
    assert TaskStore(store, isolated / "data" / "tasks").get(task_ids[0]).priority == 3
    assert verify(isolated, store).ok
    store.close()


def test_verify_reports_a_file_without_a_row_and_a_row_without_a_file(isolated):
    store, task_ids, sched_ids, trig_ids = _world(isolated)
    # a file dropped in by hand (another machine's copy)
    rec = _read(truth.truth_path(isolated, "triggers", trig_ids[0]))
    rec["id"] = "t-009"
    truth.write_truth(isolated, "triggers", "t-009", rec)
    # a row whose file went missing (never done by Jarvis; the only deletion is delete_forever)
    os.remove(truth.truth_path(isolated, "schedules", sched_ids[0]))
    report = verify(isolated, store)
    assert report.files_without_rows == [("triggers", "t-009")]
    assert report.rows_without_files == [("schedules", sched_ids[0])]
    assert not report.ok and report.summary() == "truth check: 2 difference(s), run jarvis verify"

    # rebuild creates the row from the file and reports the orphan row; it deletes nothing (law 2)
    report = rebuild(isolated, store)
    assert report.created == [("triggers", "t-009")] and report.rows_without_files == [("schedules", sched_ids[0])]
    assert not report.ok
    _, ss, tr = _stores(isolated, store)
    assert tr.get("t-009") is not None and ss.get(sched_ids[0]) is not None

    # --prune writes the orphan row out as its file first, so nothing is lost
    out = io.StringIO()
    assert cli_main(["rebuild", "--prune"], out=out) == 0
    assert f"wrote schedules {sched_ids[0]} out to its file" in out.getvalue()
    assert _read(truth.truth_path(isolated, "schedules", sched_ids[0]))["cron"] == "0 9 * * mon"
    assert ss.get(sched_ids[0]) is not None and verify(isolated, store).ok
    store.close()


def test_a_bad_file_is_reported_and_never_half_loaded(isolated):
    store, task_ids, sched_ids, trig_ids = _world(isolated)
    bad = isolated / "data" / "schedules" / "s-077.json"
    bad.write_text("{not json", encoding="utf-8")
    wrong_id = isolated / "data" / "schedules" / "s-078.json"
    truth.write_json(wrong_id, {"id": "s-001", "cron": "* * * * *"})
    report = verify(isolated, store)
    assert len(report.problems) == 2 and not report.ok
    assert any("s-077.json" in p for p in report.problems) and any("s-078.json" in p for p in report.problems)
    report = rebuild(isolated, store)
    assert report.created == [] and ScheduleStore(store.conn).get("s-077") is None
    store.close()


def test_verify_reports_task_events_missing_from_the_index(isolated):
    store, task_ids, _, _ = _world(isolated)
    truth.append_event(isolated, task_ids[0], {"ts": "2026-10-17 04:00:00", "kind": "note", "detail": "by hand"})
    report = verify(isolated, store)
    assert [d.fields for d in report.differing] == [{"events": (3, 2)}]   # created, note, then the hand-written one
    report = rebuild(isolated, store)
    assert report.events_restored == 1
    assert TaskStore(store, isolated / "data" / "tasks").events(task_ids[0])[-1]["detail"] == "by hand"
    assert verify(isolated, store).ok
    store.close()


def test_nightly_review_carries_the_truth_check(isolated):
    from jarvis.core.runtime import open_runtime
    from jarvis.proactive.review import nightly_review

    store, task_ids, sched_ids, _ = _world(isolated)
    store.close()
    rt = open_runtime()
    try:
        result = nightly_review(rt.paths.home, rt.store.conn, rt.memory, NOW)
        assert "truth check: ok" in result.summary
        assert "**Index against files:** truth check: ok" in result.path.read_text(encoding="utf-8")
        os.remove(truth.truth_path(isolated, "schedules", sched_ids[0]))
        result = nightly_review(rt.paths.home, rt.store.conn, rt.memory, NOW)
        assert "truth check: 1 difference(s), run jarvis verify" in result.summary
    finally:
        rt.close()


# ---------------------------------------------------------------- task archive (law 2)


def test_only_a_finished_task_can_be_archived_and_it_leaves_the_lists(isolated):
    store = _open(isolated)
    ts, _, _ = _stores(isolated, store)
    live = ts.create("Still running example")
    done = ts.create("Finished example")
    with pytest.raises(TransitionError):
        ts.archive(live.id, NOW)
    with pytest.raises(KeyError):
        ts.archive("t-999", NOW)
    ts.set_state(done.id, "CANCELLED", "done with it")
    archived = ts.archive(done.id, NOW)
    assert archived.archived and archived.archived_at == NOW.isoformat(timespec="seconds")
    assert archived.state == "CANCELLED"   # archive is not a state change
    assert [t.id for t in ts.list(include_final=True)] == [live.id]
    assert [t.id for t in ts.list(include_final=True, include_archived=True)] == [live.id, done.id]
    assert [e["kind"] for e in ts.events(done.id)][-1] == "archived"
    assert _read(truth.truth_path(isolated, "tasks", done.id))["archived_at"] == archived.archived_at
    assert ts.archive(done.id, NOW).archived_at == archived.archived_at   # a second archive changes nothing
    assert (isolated / "data" / "tasks" / done.id / "receipt.md").parent.exists()   # the folder stays
    back = ts.unarchive(done.id)
    assert not back.archived and [t.id for t in ts.list(include_final=True)] == [live.id, done.id]
    assert ts.unarchive(done.id).archived_at is None
    with pytest.raises(ValueError):
        ts.update(done.id, archived_at="2026-01-01")   # archive() is the only way
    store.close()


def test_task_archive_from_the_cli(isolated):
    store = _open(isolated)
    ts, _, _ = _stores(isolated, store)
    t = ts.create("Example to put away")
    ts.set_state(t.id, "CANCELLED")
    store.close()
    out = io.StringIO()
    assert cli_main(["task", "archive", t.id], out=out) == 0 and f"Archived {t.id}" in out.getvalue()
    out = io.StringIO()
    assert cli_main(["tasks", "--all"], out=out) == 0 and t.id not in out.getvalue()
    out = io.StringIO()
    assert cli_main(["tasks", "--archived"], out=out) == 0 and f"{t.id} " in out.getvalue() and "(archived)" in out.getvalue()
    out = io.StringIO()
    assert cli_main(["task", "unarchive", t.id], out=out) == 0 and f"Unarchived {t.id}" in out.getvalue()
    out = io.StringIO()
    assert cli_main(["tasks", "--all"], out=out) == 0 and t.id in out.getvalue()
    audit = (isolated / "data" / "audit.jsonl").read_text(encoding="utf-8")
    assert '"event": "task_archived"' in audit and '"event": "task_unarchived"' in audit
    # a live task cannot be archived: the reason is printed, exit 1
    store = _open(isolated)
    live = TaskStore(store, isolated / "data" / "tasks").create("Live example")
    store.close()
    out = io.StringIO()
    assert cli_main(["task", "archive", live.id], out=out) == 1 and "only a finished task" in out.getvalue()


def test_task_archive_from_the_dashboard_api(isolated, cfgdir):
    from test_web_api_app import H, _client, audit_text

    with _client(cfgdir) as c:
        tid = c.post("/api/tasks", headers=H, json={"goal": "Example task for the archive", "workspace": "personal"}).json()["id"]
        assert c.post(f"/api/tasks/{tid}/archive", headers=H).status_code == 409   # not finished
        assert c.post(f"/api/tasks/{tid}/cancel", headers=H).json()["state"] == "CANCELLED"
        d = c.post(f"/api/tasks/{tid}/archive", headers=H).json()
        assert d["state"] == "CANCELLED" and d["archived_at"]
        assert tid not in {t["id"] for t in c.get("/api/tasks", headers=H).json()["items"]}
        items = c.get("/api/tasks?archived=true", headers=H).json()["items"]
        assert next(t for t in items if t["id"] == tid)["archived_at"] == d["archived_at"]
        assert c.post(f"/api/tasks/{tid}/unarchive", headers=H).json()["archived_at"] is None
        assert tid in {t["id"] for t in c.get("/api/tasks", headers=H).json()["items"]}
        assert c.post("/api/tasks/t-999/archive", headers=H).status_code == 404
        assert c.post("/api/tasks/t-999/unarchive", headers=H).status_code == 404
    audit = audit_text(isolated)
    assert '"event": "task_archived"' in audit and '"event": "task_unarchived"' in audit
