"""Repeat-this: repetition detection, /repeat in chat and Telegram, `jarvis task repeat`, and the
unattended runs of the saved schedule. Fakes only: the skill draft comes from a scripted
FakeProvider, schedules are read by rules, clocks are fixed. All data is made up."""

import asyncio
import io
import json
import time
from datetime import datetime
from types import SimpleNamespace

import pytest

from jarvis import cli_tasks
from jarvis.cli import main
from jarvis.config import load_config
from jarvis.control.stop import StopSwitch
from jarvis.core.chat import ChatSession
from jarvis.core.runtime import open_runtime
from jarvis.db import Store
from jarvis.memory.store import MemoryStore
from jarvis.proactive.scheduler import PendingApprovals, ScheduleStore
from jarvis.providers.fake import FakeProvider
from jarvis.routing.policy import RouteDecision
from jarvis.tasks import repeat as repeat_mod
from jarvis.tasks.receipt import build_receipt
from jarvis.tasks.repeat import (
    RepeatError,
    RepeatStore,
    chat_evidence,
    confirm,
    goal_words,
    propose,
    repetition_hint,
    similar_tasks,
    similarity,
    split_task_id,
    task_evidence,
    unattended_steps,
)
from jarvis.tasks.store import TaskStore
from jarvis.telegram.bot import JarvisBot
from jarvis.telegram.core import BotCore

from test_proactive_support import FakeBot, ScriptedChats, at, button_data, proactive, update

SACHIN = 1111  # made-up Telegram id
DRAFT = {"name": "Weekly Price Check", "description": "Compare laptop prices and save a report.",
         "inputs": [{"name": "date", "description": "the day, YYYY-MM-DD"}], "preconditions": [],
         "steps": [{"text": "Search prices for {date}", "tool": "web_search"},
                   {"text": "Write prices-{date}.md", "tool": "write_file"}],
         "verify": ["prices-{date}.md exists"]}
DRAFT_WITH_APPROVAL_STEPS = {**DRAFT, "steps": DRAFT["steps"] + [
    {"text": "Replace last week's summary", "tool": "overwrite_file"},
    {"text": "Send the contact form", "tool": "browser_submit"}]}


class Drafts(list):
    """The evidence each skill-draft call was given; .use() swaps the scripted draft."""

    def __init__(self):
        super().__init__()
        self.draft = DRAFT

    def use(self, draft):
        self.draft = draft


@pytest.fixture
def drafts(monkeypatch):
    """Every skill draft call gets a scripted fake provider (no model is ever called)."""
    seen = Drafts()

    def fake_provider(name, config):
        class P(FakeProvider):
            def structured(self, req, schema):
                seen.append(req.messages[0].text_content())
                return super().structured(req, schema)
        return P(script=[{"json": seen.draft}])

    monkeypatch.setattr(repeat_mod, "make_provider", fake_provider)
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


def _task_in_db(home, goal="Compare laptop prices", state="COMPLETED"):
    store = Store(home / "data" / "jarvis.db")
    try:
        completed_task(store, home, goal, state=state)
    finally:
        store.close()


def _schedules(home):
    store = Store(home / "data" / "jarvis.db")
    try:
        return ScheduleStore(store.conn).list()
    finally:
        store.close()


def _audit(home):
    path = home / "data" / "audit.jsonl"
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


# ---- repetition ----

def test_goal_similarity_ignores_numbers_dates_and_filler():
    a = "Compare 3 laptops under Rs 80,000"
    b = "please compare laptops under rs 70000 for me"
    assert goal_words(a) == {"compare", "laptop", "under", "rs"}
    assert similarity(a, b) == 1.0
    assert similarity(a, "Book a train ticket to Pune") == 0.0
    assert similarity("Weekly report for 2026-10-05", "weekly report for 2026-10-12") == 1.0
    assert similarity("", "anything") == 0.0


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
        assert "/repeat t-006 every Monday at 9" in hint and 'jarvis task repeat t-006 "every Monday at 9"' in hint
        assert "Nothing is saved until you say yes" in hint
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


@pytest.mark.parametrize("text,expected", [
    ("t-004 every Monday at 9", ("t-004", "every Monday at 9")),
    ("T-12 daily 8am", ("t-12", "daily 8am")),
    ("every Monday at 9", (None, "every Monday at 9")),
    ("t-004", ("t-004", "")),
    ("  ", (None, "")),
    ("today at 9", (None, "today at 9")),  # "today" is not a task id
])
def test_split_task_id(text, expected):
    assert split_task_id(text) == expected


def test_unattended_steps_lists_t2_and_above_from_the_registry_tiers():
    text = ("## Steps\n1. Search — tool `web_search`, tier T0\n2. Write — tool `write_file`, tier T1\n"
            "3. Replace — tool `overwrite_file`, tier T2 (asks every time)\n"
            "4. Send — tool `browser_submit`, tier T3 (asks every time)\n5. Think about it\n")
    assert unattended_steps(text) == ["3. Replace (overwrite_file, T2)", "4. Send (browser_submit, T3)"]


# ---- jarvis task repeat ----

def test_cli_repeat_shows_draft_and_saves_only_after_yes(isolated, drafts):
    _task_in_db(isolated)

    out = io.StringIO()
    assert main(["task", "repeat", "t-001", "every", "Monday", "at", "9", "--provider", "fake"], out=out,
                inp=io.StringIO("n\n")) == 0
    text = out.getvalue()
    assert "--- SKILL.md draft ---" in text and "name: weekly-price-check" in text and "source: task t-001" in text
    assert "tool `web_search`, tier T0" in text and "tool `write_file`, tier T1" in text  # tiers from the registry
    assert "Cron: 0 9 * * mon" in text and "Runs: run skill 'weekly-price-check' (no extra input)" in text
    assert "Unattended runs may only read and write new files (T0/T1)" in text
    assert "Save this skill and schedule? [y/N]" in text and "Not saved." in text
    assert not (isolated / "skills" / "weekly-price-check").exists() and _schedules(isolated) == []
    assert list((isolated / "data" / "repeat" / "pending").iterdir()) == []  # the "no" dropped it
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
    events = [e["event"] for e in _audit(isolated)]
    assert events.count("automation_proposed") == 2 and "automation_dropped" in events
    assert "automation_saved" in events


def test_cli_repeat_has_no_way_to_skip_the_confirmation(isolated, drafts):
    _task_in_db(isolated)
    with pytest.raises(SystemExit):  # the old --yes bypass is gone
        main(["task", "repeat", "t-001", "every Monday at 9", "--provider", "fake", "--yes"], out=io.StringIO())
    out = io.StringIO()  # no answer at all (closed input, e.g. a script) means no
    assert main(["task", "repeat", "t-001", "every Monday at 9", "--provider", "fake"], out=out,
                inp=io.StringIO("")) == 0
    assert "Not saved." in out.getvalue() and _schedules(isolated) == []
    assert not (isolated / "skills").exists() or not any((isolated / "skills").iterdir())
    for answer in ("maybe\n", "yes please\n", "\n"):  # only a plain yes counts
        main(["task", "repeat", "t-001", "every Monday at 9", "--provider", "fake"], out=io.StringIO(),
             inp=io.StringIO(answer))
    assert _schedules(isolated) == []


def test_cli_repeat_refuses_unfinished_task_and_unreadable_time(isolated, drafts):
    _task_in_db(isolated, state="FAILED")
    _task_in_db(isolated)
    out = io.StringIO()
    assert main(["task", "repeat", "t-001", "every Monday at 9", "--provider", "fake"], out=out,
                inp=io.StringIO("y\n")) == 1
    assert "Only a task that completed can be made automatic (t-001 is FAILED)" in out.getvalue()
    assert "Save this skill" not in out.getvalue()
    out = io.StringIO()
    assert main(["task", "repeat", "t-002", "whenever it feels right", "--provider", "fake"], out=out,
                inp=io.StringIO("y\n")) == 1
    assert "could not read the time" in out.getvalue().lower()
    out = io.StringIO()
    assert main(["task", "repeat", "t-002", "--provider", "fake"], out=out, inp=io.StringIO("y\n")) == 1
    assert "Say when" in out.getvalue()
    out = io.StringIO()
    assert main(["task", "repeat", "t-999", "every Monday at 9", "--provider", "fake"], out=out) == 1
    assert "Give a task id" in out.getvalue()
    assert _schedules(isolated) == [] and drafts == []  # the schedule is read before any draft call


@pytest.mark.parametrize("when,ok", [
    ("every 5 minutes", False),
    ("every 15 minutes", False),
    ("every 30 minutes", True),   # exactly the limit
    ("every hour", True),
    ("every day at 21:00", True),
    ("every weekday at 8", True),
    ("on Monday at 9", False),    # a one-off is not a schedule
])
def test_repeat_schedule_edge_cases(isolated, drafts, when, ok):
    _task_in_db(isolated)
    rt = open_runtime()
    try:
        p = proactive(at(2026, 10, 10, 15, 0))
        if ok:
            proposal = propose(rt, p, when, task_id="t-001")
            assert proposal.schedule["kind"] == "skill" and proposal.schedule["target"] == "weekly-price-check"
        else:
            with pytest.raises(RepeatError):
                propose(rt, p, when, task_id="t-001")
            assert drafts == []  # refused before the model is asked to draft anything
    finally:
        rt.close()


def test_too_frequent_message_and_configurable_limit(isolated, drafts):
    _task_in_db(isolated)
    rt = open_runtime()
    try:
        with pytest.raises(RepeatError, match=r"every 5 minutes .*at most every 30 minutes"):
            propose(rt, proactive(at(2026, 10, 10, 15, 0)), "every 5 minutes", task_id="t-001")
        loose = proactive(at(2026, 10, 10, 15, 0), schedules={
            "misfire_grace_minutes": 60, "default_output": "telegram", "repeat_min_interval_minutes": 5})
        assert propose(rt, loose, "every 5 minutes", task_id="t-001").schedule["cron"] == "*/5 * * * *"
    finally:
        rt.close()


def test_draft_lists_the_steps_unattended_runs_will_not_do(isolated, drafts):
    drafts.use(DRAFT_WITH_APPROVAL_STEPS)
    _task_in_db(isolated)
    out = io.StringIO()
    main(["task", "repeat", "t-001", "every Monday at 9", "--provider", "fake"], out=out, inp=io.StringIO("n\n"))
    text = out.getvalue()
    assert "These steps need approval, so scheduled runs will NOT do them on their own" in text
    assert "3. Replace last week's summary (overwrite_file, T2)" in text
    assert "4. Send the contact form (browser_submit, T3)" in text  # browser tiers come from the registry too
    assert "1. Search prices" not in text.split("These steps need approval")[1]


def test_a_draft_expires_and_cannot_be_saved_later(isolated, drafts):
    _task_in_db(isolated)
    rt = open_runtime()
    try:
        p = proactive(at(2026, 10, 10, 15, 0))
        proposal = propose(rt, p, "every Monday at 9", task_id="t-001")
        store = RepeatStore(rt.paths.data)
        assert store.get(proposal.id) is not None
        old = json.loads((store.pending_dir / f"{proposal.id}.json").read_text(encoding="utf-8"))
        old["created_ts"] = time.time() - repeat_mod.PENDING_TTL_S - 5
        (store.pending_dir / f"{proposal.id}.json").write_text(json.dumps(old), encoding="utf-8")
        assert "expired" in confirm(rt, p, proposal.id, True)
        assert not (rt.paths.home / "skills" / "weekly-price-check").exists()
        assert ScheduleStore(rt.store.conn).list() == []
        assert list(store.pending_dir.iterdir()) == []  # the stale draft is cleaned up
        assert "expired" in confirm(rt, p, "rp-zzzzzz", True)  # not even a valid id
        assert "expired" in confirm(rt, p, "../../etc/passwd", True)
    finally:
        rt.close()


def test_a_bad_schedule_never_leaves_a_skill_saved_on_its_own(isolated, drafts):
    _task_in_db(isolated)
    rt = open_runtime()
    try:
        p = proactive(at(2026, 10, 10, 15, 0))
        proposal = propose(rt, p, "every Monday at 9", task_id="t-001")
        path = RepeatStore(rt.paths.data).pending_dir / f"{proposal.id}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["schedule"]["cron"] = "61 25 * * *"
        path.write_text(json.dumps(data), encoding="utf-8")
        assert confirm(rt, p, proposal.id, True).startswith("Not saved")
        assert not (rt.paths.home / "skills" / "weekly-price-check").exists()
        assert ScheduleStore(rt.store.conn).list() == []
    finally:
        rt.close()


def test_emergency_stop_blocks_drafting(isolated, drafts):
    _task_in_db(isolated)
    StopSwitch(isolated / "data").engage("test")
    out = io.StringIO()
    assert main(["task", "repeat", "t-001", "every Monday at 9", "--provider", "fake"], out=out,
                inp=io.StringIO("y\n")) == 1
    assert "Emergency stop is on" in out.getvalue() and drafts == [] and _schedules(isolated) == []


# ---- unattended runs of a saved automation ----

def test_saved_automation_runs_unattended_with_t0_t1_only(isolated, drafts):
    """The schedule saved by repeat goes through the normal scheduler: T1 runs, T2/T3 are refused,
    queued and listed in the run's receipt."""
    _task_in_db(isolated)
    main(["task", "repeat", "t-001", "every Monday at 9", "--provider", "fake"], out=io.StringIO(),
         inp=io.StringIO("y\n"))
    [s] = _schedules(isolated)
    ws = isolated / "workspace"
    ws.mkdir(exist_ok=True)
    (ws / "summary.md").write_text("last week", encoding="utf-8")
    chats = ScriptedChats([
        {"tool": "load_skill", "arguments": {"name": "weekly-price-check"}},
        {"tool": "write_file", "arguments": {"path": "prices-2026-10-12.md", "content": "Laptop A: Rs 75,000"}},
        {"tool": "overwrite_file", "arguments": {"path": "summary.md", "content": "this week"}},
        {"tool": "delete_file", "arguments": {"path": "summary.md"}},
        "Saved the prices; two steps need your approval.",
    ])
    p = proactive(at(2026, 10, 12, 9, 0), chats)
    result = p.runner().run(s.id, "cron")
    assert result.status == "ok" and result.pending == 2
    assert (ws / "prices-2026-10-12.md").exists()                         # T1 ran
    assert (ws / "summary.md").read_text(encoding="utf-8") == "last week"  # T2 and T3 did not
    prompt = chats.providers[0].requests[0].messages[-1].text_content()
    assert "Run the skill 'weekly-price-check'" in prompt and "Sachin is not watching" in prompt
    assert "- #1 overwrite_file (T2): refused unattended, waiting for approval" in result.text
    assert "- #2 delete_file (T3): refused unattended, waiting for approval" in result.text
    rt = open_runtime()
    try:
        [run] = ScheduleStore(rt.store.conn).runs(s.id)
        assert "overwrite_file (T2)" in run["detail"] and "delete_file (T3)" in run["detail"]  # the run receipt
        pending = PendingApprovals(rt.store.conn).list()
        assert [(a["tool"], a["tier"]) for a in pending] == [("overwrite_file", "T2"), ("delete_file", "T3")]
    finally:
        rt.close()


# ---- /repeat in the terminal chat ----

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
        assert "Not saved" in out.getvalue() and RepeatStore(rt.paths.data).latest(s2.session_id) is None
        assert ScheduleStore(rt.store.conn).list() == []
    finally:
        rt.close()


def test_chat_repeat_with_nothing_done_yet(isolated, drafts):
    rt = open_runtime()
    try:
        out = io.StringIO()
        cli_tasks.chat_command(chat(rt, []), rt, "/repeat", "every day at 8", out)
        assert "Nothing to repeat yet" in out.getvalue() and drafts == []
    finally:
        rt.close()


def test_another_chat_cannot_confirm_this_chats_draft(isolated, drafts):
    rt = open_runtime()
    try:
        s = chat(rt, ["Here is the weather, sir."])
        s.send("what's the weather")
        cli_tasks.chat_command(s, rt, "/repeat", "every day at 8", io.StringIO())
        other = chat(rt, [])
        out = io.StringIO()
        cli_tasks.chat_command(other, rt, "/repeat", "yes", out)
        assert "Nothing is waiting" in out.getvalue() and ScheduleStore(rt.store.conn).list() == []
        assert RepeatStore(rt.paths.data).latest(s.session_id) is not None  # still waiting for its own chat
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


def test_chat_repeat_with_an_explicit_task_id(isolated, drafts):
    rt = open_runtime()
    try:
        s = chat(rt, [])
        completed_task(rt.store, rt.paths.home, "Compare laptop prices")
        out = io.StringIO()
        cli_tasks.chat_command(s, rt, "/repeat", "t-001 every day at 21:00", out)
        assert "Automation from task t-001" in out.getvalue() and "Cron: 0 21 * * *" in out.getvalue()
        cli_tasks.chat_command(s, rt, "/repeat", "nako", io.StringIO())
        assert ScheduleStore(rt.store.conn).list() == []
    finally:
        rt.close()


# ---- /repeat on Telegram ----

def _bot(chats=None):
    p = proactive(at(2026, 10, 10, 15, 0), chats or ScriptedChats())
    core = BotCore(p, SACHIN)
    return JarvisBot(core, approval_timeout=5, bot=FakeBot()), core


def _cmd(bot, text):
    u = update(SACHIN, text)
    asyncio.run(bot.on_command(u, None))
    return u.effective_message.replies


def _press(bot, data):
    q = update(SACHIN, data=data)
    asyncio.run(bot.on_callback(q, None))
    return q.callback_query.edits[0]


def test_telegram_repeat_needs_something_to_repeat(isolated, drafts):
    bot, _ = _bot()
    shown, markup = _cmd(bot, "/repeat every day at 8")[0]
    assert markup is None and "Nothing to repeat yet" in shown
    shown, markup = _cmd(bot, "/repeat")[0]
    assert markup is None and "Say when" in shown
    assert drafts == []


def test_telegram_repeat_last_chat_action_saved_only_by_the_save_button(isolated, drafts):
    chats = ScriptedChats([{"tool": "write_file", "arguments": {"path": "prices.md", "content": "Laptop A"}},
                           "Saved the prices, sir."])
    bot, _ = _bot(chats)
    u = update(SACHIN, "save today's laptop prices")
    asyncio.run(bot.on_text(u, None))
    replies = _cmd(bot, "/repeat every day at 21:00")
    shown, markup = replies[-1]
    full = "\n".join(r[0] for r in replies)
    assert "Automation draft rp-" in full and "Cron: 0 21 * * *" in full and "Save this skill and schedule?" in shown
    # Telegram is a cloud service: no skill text, goal or step wording goes there (P2 may hide in them)
    assert "--- SKILL.md draft ---" not in full and "save today's laptop prices" not in full
    assert "jarvis task draft rp-" in full
    assert "save today's laptop prices" in drafts[0]
    assert _schedules(isolated) == [] and not (isolated / "skills" / "weekly-price-check").exists()
    save, cancel = button_data(markup)
    assert save.startswith("rp:rp-") and save.endswith(":y")
    edit = _press(bot, save)
    assert edit.startswith("Saved skill weekly-price-check") and "s-001" in edit
    assert (isolated / "skills" / "weekly-price-check" / "SKILL.md").exists()
    [s] = _schedules(isolated)
    assert (s.kind, s.target, s.source) == ("skill", "weekly-price-check", "repeat")
    assert "already answered" in _press(bot, save)  # pressing Save twice saves once
    assert len(_schedules(isolated)) == 1
    assert any(e["event"] == "automation_saved" and e["channel"] == "telegram" for e in _audit(isolated))


def test_telegram_repeat_cancel_and_task_id(isolated, drafts):
    _task_in_db(isolated)
    bot, _ = _bot()
    shown, markup = _cmd(bot, "/repeat t-001 every Monday at 9")[-1]
    assert markup is not None
    assert _press(bot, button_data(markup)[1]) == "Not saved."
    assert _schedules(isolated) == [] and not (isolated / "skills" / "weekly-price-check").exists()
    shown, markup = _cmd(bot, "/repeat t-001 every 5 minutes")[-1]
    assert markup is None and "at most every 30 minutes" in shown


def test_telegram_repeat_respects_the_emergency_stop(isolated, drafts):
    _task_in_db(isolated)
    bot, core = _bot()
    core.cmd_stop("test")
    shown, markup = _cmd(bot, "/repeat t-001 every Monday at 9")[-1]
    assert markup is None and "Emergency stop is ON" in shown and drafts == []


def test_telegram_registers_repeat_and_lists_it_in_help():
    bot, _ = _bot()
    from telegram.ext import CommandHandler

    app = bot.build("123456:TEST-token-not-real")
    names = {c for h in app.handlers[0] if isinstance(h, CommandHandler) for c in h.commands}
    assert "repeat" in names
    from jarvis.telegram.core import HELP

    assert "/repeat <when>" in HELP


def test_telegram_draft_summary_hides_text_and_cli_shows_the_full_draft(isolated, drafts):
    import io
    import re as _re

    from jarvis.cli import main as cli_main

    chats = ScriptedChats([{"tool": "write_file", "arguments": {"path": "prices.md", "content": "Laptop A"}},
                           "Saved the prices, sir."])
    bot, _ = _bot(chats)
    asyncio.run(bot.on_text(update(SACHIN, "save today's laptop prices"), None))
    full = "\n".join(r[0] for r in _cmd(bot, "/repeat every day at 21:00"))
    pid = _re.search(r"rp-[0-9a-f]{6}", full).group()
    out = io.StringIO()
    assert cli_main(["task", "draft", pid], out=out) == 0
    local = out.getvalue()
    assert "--- SKILL.md draft ---" in local and "Automation from chat" in local
    assert _schedules(isolated) == []                       # viewing never saves
    out = io.StringIO()
    assert cli_main(["task", "draft", "rp-000000"], out=out) == 1


def test_confirm_result_is_structured_and_confirm_keeps_its_message(isolated, drafts):
    from types import SimpleNamespace

    from jarvis.core.runtime import open_runtime
    from jarvis.tasks.repeat import confirm, confirm_result

    rt = open_runtime()
    try:
        p = SimpleNamespace(now=lambda: at(2026, 10, 10, 15, 0), grace_s=3600)
        r = confirm_result(rt, p, "rp-000000", True)
        assert (r.status, r.saved) == ("expired", False) and "expired" in r.message
        assert confirm(rt, p, "rp-000000", True) == r.message
    finally:
        rt.close()
