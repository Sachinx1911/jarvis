"""Step 1 wiring: an office's fence and daily budget reach a running task (PLAN.md 27.3, 27.4).

Uses the task fakes of tests/test_tasks_team.py; no model, no network.
"""

from __future__ import annotations

from dataclasses import replace

from jarvis.workspaces.model import Budget
from jarvis.workspaces.store import WorkspaceStore
from tests.test_tasks_team import PLAN_TEAM, _runner, env  # noqa: F401


def _office(home, **changes):
    ws = WorkspaceStore(home)
    w = ws.create("acme", "Acme Ltd", "company", "demo office")
    return ws.save(replace(w, **changes))


def test_office_fence_stops_a_denied_tool_in_a_team_task(env):
    home, store = env
    _office(home, tools_deny=("web_search",))
    runner, ts, providers = _runner(env, PLAN_TEAM)
    t = ts.create("Compare 3 laptops under Rs 80,000", workspace="acme")
    runner.run(t.id)
    # the researchers asked for web_search and got the fence's refusal, audited as tool_fenced
    audit = (home / "data" / "audit.jsonl").read_text(encoding="utf-8")
    assert "tool_fenced" in audit and "denied in workspace acme" in audit
    # and web_search never ran for this task
    runs = store.conn.execute("SELECT tool, ok FROM tool_runs WHERE task_id=?", (t.id,)).fetchall()
    assert not any(tool == "web_search" and ok for tool, ok in runs), runs


def test_office_daily_budget_stops_a_task(env):
    home, store = env
    _office(home, budget=Budget(max_model_calls=1))
    runner, ts, _ = _runner(env, PLAN_TEAM)
    t = ts.create("Compare 3 laptops under Rs 80,000", workspace="acme")
    done = runner.run(t.id)
    assert done.state == "FAILED" and "loka budget" in (done.last_error or "")
    audit = (home / "data" / "audit.jsonl").read_text(encoding="utf-8")
    assert "loka_capped" in audit
    # the personal office is not capped by acme's budget
    t2 = ts.create("Compare 3 laptops under Rs 80,000")
    assert _runner(env, PLAN_TEAM)[0].run(t2.id).state == "COMPLETED"


def test_narada_request_result_crosses_back_after_the_task_runs(env):
    """27.5 item 6: personal asks acme; acme's court runs it; only the deliverable crosses back."""
    from jarvis.workspaces.narada import RequestStore

    home, store = env
    _office(home)
    runner, ts, _ = _runner(env, PLAN_TEAM)
    req = RequestStore(store.conn, home, runner.audit).ask("personal", "acme", "Compare 3 laptops under Rs 80,000", ts)
    task = ts.get(req.task_id)
    assert task.workspace == "acme" and req.state == "requested"
    assert runner.run(task.id).state == "COMPLETED"
    done = RequestStore(store.conn, home).get(req.id)
    assert done.state == "done" and done.result
    inbox = home / "data" / "workspaces" / "personal" / "inbox"
    assert inbox.exists() and any(p.name.startswith(task.id) for p in inbox.iterdir()), list(inbox.iterdir())
    assert "loka_request_delivered" in (home / "data" / "audit.jsonl").read_text(encoding="utf-8")
