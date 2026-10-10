""""Do this every time": repetition detection, /repeat in chat and `jarvis task repeat`.
Fakes only: the skill draft comes from a scripted FakeProvider, schedules are read by rules."""

import io
import json
from datetime import datetime
from types import SimpleNamespace

import pytest

from jarvis import cli_tasks
from jarvis.cli import main
from jarvis.config import load_config
from jarvis.core.chat import ChatSession
from jarvis.core.runtime import open_runtime
from jarvis.db import Store
from jarvis.memory.store import MemoryStore
from jarvis.providers.fake import FakeProvider
from jarvis.routing.policy import RouteDecision
from jarvis.tasks.receipt import build_receipt
from jarvis.tasks.repeat import (
    RepeatError,
    RepeatStore,
    chat_evidence,
    goal_words,
    repetition_hint,
    similar_tasks,
    similarity,
    task_evidence,
)
from jarvis.tasks.store import TaskStore

DRAFT = {"name": "Weekly Price Check", "description": "Compare laptop prices and save a report.",
         "inputs": [{"name": "date", "description": "the day, YYYY-MM-DD"}], "preconditions": [],
         "steps": [{"text": "Search prices for {date}", "tool": "web_search"},
                   {"text": "Write prices-{date}.md", "tool": "write_file"}],
         "verify": ["prices-{date}.md exists"]}


@pytest.fixture
def drafts(monkeypatch):
    """Every skill draft call gets a scripted fake; records the evidence it was given."""
    seen = []

    def fake_provider(name, config):
        class P(FakeProvider):
            def structured(self, req, schema):
                seen.append(req.messages[0].text_content())
                return super().structured(req, schema)
        return P(script=[{"json": DRAFT}])

    monkeypatch.setattr(cli_tasks, "make_provider", fake_provider)
    return seen


def completed_task(store, home, goal, days_ago=0, state="COMPLETED"):
    ts = TaskStore(store, home / "data" / "tasks")
    t = ts.create(goal)
    store.conn.execute("UPDATE tasks SET state=?, created_at=datetime('now', ?), plan=?, checkpoint=? WHERE id=?",
                       (state, f"-{days_ago} days", json.dumps({"mode": "answer", "use_team": False, "research": [],
                                                                "acceptance_criteria": ["has prices"],
                                                                "deliverable": {"filename": "result.md",
                                                                                "outline": "table"},
                                                                "solo_instructions": goal}),
                        json.dumps({"report": "result.md"}), t.id))
    store.conn.execute("INSERT INTO tool_runs (task_id, tool, tier, arguments, result, ok, agent) VALUES "
                       "(?, 'web_search', 'T0', '{\"query\": \"laptop prices\"}', 'results', 1, 'jarvis')", (t.id,))
    store.conn.commit()
    (ts.folder(t.id) / "result.md").write_text("| Laptop A | Rs 75,000 |", encoding="utf-8")
    return ts, ts.get(t.id)


# ---- repetition ----

def test_goal_similarity_ignores_numbers_dates_and_filler():
    a = "Compare 3 laptops under Rs 80,000"
    b = "please compare laptops under rs 70000 for me"
    assert goal_words(a) == {"compare", "laptop", "under", "rs"}
    assert similarity(a, b) == 1.0
    assert similarity(a, "Book a train ticket to Pune") == 0.0
    assert similarity("Weekly report for 2026-10-05", "weekly report for 2026-10-12") == 1.0


def test_three_similar_runs_in_30_days_suggest_automation(isolated):
    store = Store(isolated / "data" / "jarvis.db")
    try:
        completed_task(store, isolated, "Compare laptop prices under Rs 80,000", days_ago=40)  # too old
        completed_task(store, isolated, "Compare laptop prices under Rs 80,000", days_ago=10)
        ts, t = completed_task(store, isolated, "compare laptop prices under Rs 75000")
        completed_task(store, isolated, "Book a train ticket")
        assert repetition_hint(ts, t) is None  # only 2 in the window
        ts, t3 = completed_task(store, isolated, "Please compare laptop prices under 90000", state="FAILED")
        ts, t4 = completed_task(store, isolated, "Compare laptop prices under Rs 80,000")
        assert similar_tasks(ts, t4) == ["t-002", "t-003", "t-005", "t-006"]
        hint = repetition_hint(ts, t4)
        assert hint.startswith("Make this automatic? This kind of task ran 4 times in the last 30 days")
        assert "/repeat every Monday at 9" in hint and 'jarvis task repeat t-006 "every Monday at 9"' in hint
        assert repetition_hint(ts, t3) is None  # only a completed task gets the suggestion
        receipt = build_receipt(SimpleNamespace(tasks=ts, store=store), t4.id)
        assert "Make this automatic?" in receipt
    finally:
        store.close()


def test_hint_stops_once_automated(isolated):
    store = Store(isolated / "data" / "jarvis.db")
    try:
        for _ in range(3):
            ts, t = completed_task(store, isolated, "Compare laptop prices")
        assert repetition_hint(ts, t)
        RepeatStore(isolated / "data").saved_file.parent.mkdir(parents=True, exist_ok=True)
        RepeatStore(isolated / "data").saved_file.write_text(
            json.dumps({"words": sorted(goal_words("compare laptop prices"))}) + "\n", encoding="utf-8")
        assert repetition_hint(ts, t) is None
    finally:
        store.close()


def test_task_evidence_has_goal_plan_runs_and_output(isolated):
    store = Store(isolated / "data" / "jarvis.db")
    try:
        ts, t = completed_task(store, isolated, "Compare laptop prices")
        ev = task_evidence(store.conn, ts, t)
        assert "- user: Compare laptop prices" in ev and "- acceptance: has prices" in ev
        assert "web_search (T0)" in ev and "| Laptop A | Rs 75,000 |" in ev and "## Browser steps" in ev
    finally:
        store.close()


# ---- jarvis task repeat ----

def _schedules(home):
    rt_store = Store(home / "data" / "jarvis.db")
    try:
        from jarvis.proactive.scheduler import ScheduleStore

        return ScheduleStore(rt_store.conn).list()
    finally:
        rt_store.close()


def test_cli_repeat_shows_draft_and_saves_only_after_yes(isolated, drafts):
    store = Store(isolated / "data" / "jarvis.db")
    completed_task(store, isolated, "Compare laptop prices")
    store.close()

    out = io.StringIO()
    assert main(["task", "repeat", "t-001", "every", "Monday", "at", "9", "--provider", "fake"], out=out,
                inp=io.StringIO("n\n")) == 0
    text = out.getvalue()
    assert "--- SKILL.md draft ---" in text and "name: weekly-price-check" in text and "source: task t-001" in text
    assert "tool `web_search`, tier T0" in text and "tool `write_file`, tier T1" in text  # tiers from the registry
    assert "Cron: 0 9 * * mon" in text and "Runs: run skill 'weekly-price-check'" in text
    assert "Not saved." in text
    assert not (isolated / "skills" / "weekly-price-check").exists() and _schedules(isolated) == []
    assert "Compare laptop prices" in drafts[0] and "every Monday at 9" in drafts[0]

    out = io.StringIO()
    assert main(["task", "repeat", "t-001", "every Monday at 9", "--provider", "fake"], out=out,
                inp=io.StringIO("y\n")) == 0
    assert "Saved skill weekly-price-check" in out.getvalue()
    skill = (isolated / "skills" / "weekly-price-check" / "SKILL.md").read_text(encoding="utf-8")
    assert "source: task t-001" in skill
    [s] = _schedules(isolated)
    assert (s.kind, s.target, s.cron, s.source) == ("skill", "weekly-price-check", "0 9 * * mon", "repeat")
    saved = RepeatStore(isolated / "data").saved()
    assert saved[0]["schedule_id"] == s.id and list((isolated / "data" / "repeat" / "pending").iterdir()) == []


def test_cli_repeat_refuses_unfinished_task_and_unreadable_time(isolated, drafts):
    store = Store(isolated / "data" / "jarvis.db")
    completed_task(store, isolated, "Compare laptop prices", state="FAILED")
    completed_task(store, isolated, "Compare laptop prices")
    store.close()
    out = io.StringIO()
    assert main(["task", "repeat", "t-001", "every Monday at 9", "--provider", "fake", "--yes"], out=out) == 1
    assert "Only a task that completed can be made automatic (t-001 is FAILED)" in out.getvalue()
    out = io.StringIO()
    assert main(["task", "repeat", "t-002", "whenever it feels right", "--provider", "fake", "--yes"], out=out) == 1
    assert "could not read the time" in out.getvalue().lower()
    assert _schedules(isolated) == [] and drafts == []  # the schedule is read before any draft call


# ---- /repeat in chat ----

def chat(rt, script):
    decision = RouteDecision("main_chat", "fake", "fake-1", "medium", "test")
    from jarvis.control.audit import AuditLog

    return ChatSession(load_config(), FakeProvider(script=script), decision, rt.store,
                       AuditLog(rt.paths.home / "data" / "audit.jsonl"), now=lambda: datetime(2026, 10, 10, 9, 0),
                       home=rt.paths.home, memory=MemoryStore(rt.paths.home, rt.store))


def test_chat_repeat_last_action_then_yes(isolated, drafts):
    rt = open_runtime()
    try:
        s = chat(rt, [{"tool": "write_file", "arguments": {"path": "notes/prices.md", "content": "Laptop A"}},
                      "Saved the price list, sir."])
        s.send("save today's laptop prices to notes")
        out = io.StringIO()
        assert cli_tasks.chat_command(s, rt, "/repeat", "", out)
        assert "Usage: /repeat <when>" in out.getvalue()
        out = io.StringIO()
        cli_tasks.chat_command(s, rt, "/repeat", "every day at 21:00", out)
        text = out.getvalue()
        assert "Automation from chat " in text and "Cron: 0 21 * * *" in text
        assert "Reply /repeat yes to save" in text
        assert "save today's laptop prices to notes" in drafts[0] and "write_file (T1)" in drafts[0]
        assert not (rt.paths.home / "skills" / "weekly-price-check").exists()  # nothing saved yet
        out = io.StringIO()
        cli_tasks.chat_command(s, rt, "/repeat", "yes", out)
        assert "Saved skill weekly-price-check" in out.getvalue()
        assert (rt.paths.home / "skills" / "weekly-price-check" / "SKILL.md").exists()
        out = io.StringIO()
        cli_tasks.chat_command(s, rt, "/repeat", "yes", out)
        assert "Nothing is waiting" in out.getvalue()
    finally:
        rt.close()


def test_chat_repeat_no_drops_and_failed_action_is_refused(isolated, drafts):
    rt = open_runtime()
    try:
        s = chat(rt, [{"tool": "write_file", "arguments": {"path": "../outside.txt", "content": "x"}},
                      "I could not save it, sir."])
        s.send("save a file outside")
        with pytest.raises(RepeatError, match="did not fully succeed"):
            chat_evidence(rt.store.conn, s.session_id)
        out = io.StringIO()
        cli_tasks.chat_command(s, rt, "/repeat", "every day at 8", out)
        assert "did not fully succeed" in out.getvalue() and drafts == []

        s2 = chat(rt, ["Here is the weather, sir."])
        s2.send("what's the weather")
        cli_tasks.chat_command(s2, rt, "/repeat", "every day at 8", io.StringIO())
        out = io.StringIO()
        cli_tasks.chat_command(s2, rt, "/repeat", "no", out)
        assert "Dropped" in out.getvalue() and RepeatStore(rt.paths.data).latest(s2.session_id) is None
    finally:
        rt.close()


def test_chat_repeat_after_task_uses_the_task(isolated, drafts):
    rt = open_runtime()
    try:
        s = chat(rt, [])
        completed_task(rt.store, rt.paths.home, "Compare laptop prices")
        s.last_task_id = "t-001"  # what /task sets
        out = io.StringIO()
        cli_tasks.chat_command(s, rt, "/repeat", "every Monday at 9", out)
        assert "Automation from task t-001" in out.getvalue()
        out = io.StringIO()
        cli_tasks.chat_command(s, rt, "/repeat", "yes", out)
        assert "Saved schedule s-001" in out.getvalue()
    finally:
        rt.close()
