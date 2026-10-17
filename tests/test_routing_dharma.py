"""Dharma routing (PLAN.md 27.5 step 2, 27.8 decision 4): a task goes to the office whose duties it
matches; personal when nothing matches; Jarvis asks when unsure; an office Sachin set is never
re-routed; every routing is in the audit log (law 3). Deterministic, both scripts, no model."""

from __future__ import annotations

import io
import json
from dataclasses import replace
from datetime import datetime

import pytest

from jarvis import cli_tasks
from jarvis.config import load_config
from jarvis.control.audit import AuditLog
from jarvis.core.chat import ChatSession
from jarvis.core.runtime import open_runtime
from jarvis.memory.store import MemoryStore
from jarvis.providers.fake import FakeProvider
from jarvis.routing.policy import RouteDecision
from jarvis.workspaces.model import PERSONAL, Workspace
from jarvis.workspaces.routing import SURE_CONFIDENCE, keys, route
from jarvis.workspaces.store import WorkspaceStore

P = Workspace("personal", "Personal", "personal")
DM = Workspace("digital-marketing", "Digital Marketing", duties=("ads", "social media posts", "client reports"),
               projects=("acme-ads",), brief="Runs ad campaigns for clients")
RE = Workspace("spardha", "Spardha Realty", duties=("property listings", "site visits"),
               brief="Real estate reels")


# ---- the pure rule ----

def test_personal_is_the_default_when_nothing_matches():
    r = route("buy milk and call mother", [P, DM, RE])
    assert r.slug == PERSONAL and r.sure and r.confidence == 1.0
    assert "personal is the default" in r.reasons[0]
    assert r.candidates[0].slug == PERSONAL
    only = route("plan the ads", [P])
    assert only.slug == PERSONAL and only.sure and "only the personal workspace" in only.reasons[0]


def test_a_duty_word_routes_surely_with_the_reason():
    r = route("Plan this week's Instagram ads for Acme", [P, DM, RE])
    assert r.slug == "digital-marketing" and r.sure
    assert r.line() == "Routed to Digital Marketing (duties: ads; projects: acme, ads)"
    assert r.candidates[0].slug == "digital-marketing" and r.candidates[-1].slug == PERSONAL


def test_both_scripts_meet_at_one_key():
    assert keys("जाहिरात posts") == {"jahirat", "posts"}
    mr = Workspace("dm", "Marketing", duties=("jahirat", "social media posts"))
    r = route("आजचे जाहिरात posts तयार कर", [P, mr])
    assert r.slug == "dm" and r.sure and "duties: posts, जाहिरात" in r.line()
    r = route("jahirat banva", [P, Workspace("dm", "Marketing", duties=("जाहिरात",))])
    assert r.slug == "dm" and r.sure


def test_unsure_when_two_offices_score_alike_or_the_match_is_weak():
    close = route("posts about the new listings", [P, DM, RE])  # a duty word for each office
    assert close.slug is None and not close.sure and close.confidence < SURE_CONFIDENCE
    assert close.reasons[-1] == "asking: two offices score alike"
    assert [c.slug for c in close.candidates] == ["digital-marketing", "spardha", "personal"]
    assert close.line().startswith("Which office is this for? 1. Digital Marketing, 2. Spardha Realty, 3. Personal")
    weak = route("edit the reels", [P, DM, RE])   # only a brief word matched
    assert weak.slug is None and "best score is low" in weak.reasons[-1]
    assert [c.slug for c in weak.candidates] == ["spardha", "personal"]


def test_routing_is_deterministic_and_ignores_archived_offices():
    goal = "client report on last month's ads"
    assert route(goal, [P, DM, RE]) == route(goal, [RE, DM, P])
    gone = Workspace("digital-marketing", "Digital Marketing", duties=("ads",), archived=True)
    assert route(goal, [P, gone, RE]).slug == PERSONAL


# ---- the chat: /task routes, /workspace pins, /project owns ----

def _chat(rt):
    decision = RouteDecision("main_chat", "fake", "fake-1", "medium", "test")
    return ChatSession(load_config(), FakeProvider(), decision, rt.store, AuditLog(rt.paths.home / "data" / "audit.jsonl"),
                       now=lambda: datetime(2026, 10, 17, 9, 0), home=rt.paths.home,
                       memory=MemoryStore(rt.paths.home, rt.store))


def _offices(home):
    ws = WorkspaceStore(home)
    ws.save(replace(ws.create("digital-marketing", "Digital Marketing"), duties=("ads", "posts")))
    ws.save(replace(ws.create("spardha", "Spardha Realty"), duties=("listings", "site visits")))
    return ws


def _routed_events(home):
    return [json.loads(l) for l in (home / "data" / "audit.jsonl").read_text(encoding="utf-8").splitlines()
            if '"task_routed"' in l]


@pytest.fixture
def capture(monkeypatch):
    calls = []
    monkeypatch.setattr(cli_tasks, "create_task", lambda rt, goal, project=None, **kw: calls.append((goal, project, kw)) or "t-1")
    monkeypatch.setattr(cli_tasks, "run_task", lambda rt, tid, out, approver, *a, **k: calls.append(("run", tid)) or 0)
    return calls


def test_slash_task_routes_when_no_office_is_set(isolated, capture):
    rt = open_runtime()
    try:
        _offices(isolated)
        s = _chat(rt)
        out = io.StringIO()
        assert cli_tasks.chat_command(s, rt, "/task", "plan next week's ads", out, io.StringIO(""))
        assert out.getvalue().startswith("Routed to Digital Marketing (duties: ads)")
        assert capture[0][2]["workspace"] == "digital-marketing" and capture[1] == ("run", "t-1")
        [ev] = _routed_events(isolated)
        assert ev["workspace"] == "digital-marketing" and ev["source"] == "auto" and ev["reasons"]
        assert s.workspace == PERSONAL  # the chat itself stays where it was
    finally:
        rt.close()


def test_slash_task_asks_when_unsure_and_takes_the_number(isolated, capture):
    rt = open_runtime()
    try:
        _offices(isolated)
        s = _chat(rt)
        out = io.StringIO()
        cli_tasks.chat_command(s, rt, "/task", "posts about the listings", out, io.StringIO("2\n"))
        text = out.getvalue()
        assert "Which office is this for? 1. Digital Marketing, 2. Spardha Realty, 3. Personal" in text
        assert capture[0][2]["workspace"] == "spardha"
        [ev] = _routed_events(isolated)
        assert ev["workspace"] == "spardha" and ev["source"] == "user"
        # a name works too; an empty answer starts nothing
        capture.clear()
        cli_tasks.chat_command(s, rt, "/task", "posts about the listings", io.StringIO(), io.StringIO("personal\n"))
        assert capture[0][2]["workspace"] == PERSONAL
        capture.clear()
        out = io.StringIO()
        cli_tasks.chat_command(s, rt, "/task", "posts about the listings", out, io.StringIO("\n"))
        assert "Not started" in out.getvalue() and capture == []
        assert _routed_events(isolated)[-1]["source"] == "cancelled"
    finally:
        rt.close()


def test_an_office_sachin_set_is_never_rerouted(isolated, capture):
    rt = open_runtime()
    try:
        _offices(isolated)
        s = _chat(rt)
        cli_tasks.chat_command(s, rt, "/workspace", "spardha", io.StringIO())
        out = io.StringIO()
        cli_tasks.chat_command(s, rt, "/task", "plan next week's ads", out, io.StringIO(""))
        assert "Routed" not in out.getvalue() and capture[0][2]["workspace"] == "spardha"
        assert _routed_events(isolated) == []
        cli_tasks.chat_command(s, rt, "/workspace", "off", io.StringIO())  # back to routing
        capture.clear()
        cli_tasks.chat_command(s, rt, "/task", "plan next week's ads", io.StringIO(), io.StringIO(""))
        assert capture[0][2]["workspace"] == "digital-marketing"
    finally:
        rt.close()


def test_a_project_owns_its_tasks(isolated, capture):
    from jarvis.projects import ProjectStore

    rt = open_runtime()
    try:
        ws = _offices(isolated)
        ProjectStore(isolated).create("site-video", "reels")
        ws.save(replace(ws.get("spardha"), projects=("site-video",)))
        s = _chat(rt)
        cli_tasks.chat_command(s, rt, "/project", "site-video", io.StringIO())
        cli_tasks.chat_command(s, rt, "/task", "plan next week's ads", io.StringIO(), io.StringIO(""))
        assert capture[0][1] == "site-video" and capture[0][2]["workspace"] == "spardha"
        assert _routed_events(isolated) == []
    finally:
        rt.close()


def test_only_personal_routes_silently(isolated, capture):
    rt = open_runtime()
    try:
        s = _chat(rt)
        out = io.StringIO()
        cli_tasks.chat_command(s, rt, "/task", "plan next week's ads", out, io.StringIO(""))
        assert "Routed" not in out.getvalue() and capture[0][2]["workspace"] == PERSONAL
        assert _routed_events(isolated)[0]["workspace"] == PERSONAL
    finally:
        rt.close()


# ---- jarvis task add: --workspace, or routing with a prompt ----

def test_cli_task_add_routes_or_asks(isolated):
    from jarvis.cli import main
    from jarvis.core.runtime import task_store

    _offices(isolated)
    out = io.StringIO()
    assert main(["task", "add", "plan next week's ads"], out, io.StringIO("")) == 0
    assert "Routed to Digital Marketing" in out.getvalue()
    out = io.StringIO()
    assert main(["task", "add", "posts about the listings"], out, io.StringIO("1\n")) == 0
    assert "Which office" in out.getvalue()
    out = io.StringIO()
    assert main(["task", "add", "posts about the listings"], out, io.StringIO("\n")) == 1
    assert main(["task", "add", "--workspace", "spardha", "posts about the listings"], io.StringIO(), io.StringIO("")) == 0
    rt = open_runtime()
    try:
        tasks = task_store(rt).list()
        assert sorted(t.workspace for t in tasks) == ["digital-marketing", "digital-marketing", "spardha"]
    finally:
        rt.close()
