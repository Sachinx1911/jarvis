"""Phase 3: task states, team orchestration, verification, receipts, budgets, resume."""

import json

import pytest

from jarvis.config import load_config
from jarvis.control.audit import AuditLog
from jarvis.control.stop import StopSwitch
from jarvis.db import Store
from jarvis.projects import ProjectStore
from jarvis.providers.base import LLMResponse, ToolCall, Usage
from jarvis.providers.fake import FakeProvider
from jarvis.secrets import set_secret
from jarvis.tasks.store import TaskStore, TransitionError
from jarvis.tools.web import WebClient

SRC = "https://shop.example/laptop-a"


class RoleFake(FakeProvider):
    """Stateless per-agent behaviour, safe for parallel researchers."""

    def __init__(self, role, report_text=None, verdicts=None):
        super().__init__()
        self.role = role
        self.report_text = report_text or [f"# Compare\n| Laptop A | Rs 75,000 | {SRC} |\nRecommendation: Laptop A."]
        self.verdicts = verdicts or [{"passed": True, "checks": [{"criterion": "3 laptops", "passed": True}], "problems": []}]
        self.writes = 0
        self.checks = 0

    def generate(self, req):
        self.requests.append(req)
        last = req.messages[-1]
        after_tool = last.role == "tool"
        calls, text = [], ""
        if self.role == "researcher":
            if after_tool:
                text = f"FINDINGS:\n- Laptop A costs Rs 75,000\nSOURCES:\n- Shop - {SRC}\nGAPS: none"
            else:
                calls = [ToolCall("c1", "web_search", {"query": "laptop under 80000"})]
        elif self.role == "writer":
            if after_tool:
                text = "Created the report."
            else:
                body = self.report_text[min(self.writes, len(self.report_text) - 1)]
                fname = req.messages[0].text_content().split("Create the file ")[1].split(" with")[0]
                calls = [ToolCall("w1", "write_file", {"path": fname, "content": body})]
                self.writes += 1
        elif self.role == "checker":
            if after_tool:
                text = json.dumps(self.verdicts[min(self.checks, len(self.verdicts) - 1)])
                self.checks += 1
            else:
                fname = req.messages[0].text_content().split("report file ")[1].split(" for")[0]
                calls = [ToolCall("r1", "read_file", {"path": fname})]
        elif self.role == "main_chat":
            text = "Laptop A at Rs 75,000 is the best pick, sir."
        return LLMResponse(text, calls, "tool_use" if calls else "end", Usage(1000, 200), "fake", req.model, 0,
                           cost_usd=None, adapter_state={"notional_usd": 0.01})


PLAN_TEAM = {"title": "Laptop compare", "use_team": True,
             "research": [{"objective": "find laptops under Rs 80,000", "focus": "Dell and HP"},
                          {"objective": "find laptops under Rs 80,000", "focus": "Lenovo and Asus"}],
             "deliverable": {"filename": "Laptop Compare.md", "outline": "table + recommendation"},
             "acceptance_criteria": ["3 laptops under Rs 80,000", "every price has a link"], "solo_instructions": ""}
PLAN_SOLO = {**PLAN_TEAM, "use_team": False, "research": [], "solo_instructions": "Answer directly"}


def _transport(method, url, headers, body):
    return 200, json.dumps({"results": [{"title": "Shop", "url": SRC, "content": "Laptop A Rs 75,000"}]}).encode()


@pytest.fixture
def env(isolated):
    set_secret("tavily_api_key", "tvly-test")
    store = Store(isolated / "data" / "jarvis.db")
    yield isolated, store
    store.close()


def _runner(env, plan, roles=None, budget=None, **kw):
    from jarvis.agents.orchestrator import TaskRunner

    home, store = env
    roles = roles or {}
    providers = {
        "planner": FakeProvider(script=[{"json": plan}]),
        "task_summary": FakeProvider(script=[{"json": {"summary": "Compared laptops."}}] * 5),
        "quarantine": FakeProvider(),
        "researcher": roles.get("researcher") or RoleFake("researcher"),
        "writer": roles.get("writer") or RoleFake("writer"),
        "checker": roles.get("checker") or RoleFake("checker"),
        "main_chat": RoleFake("main_chat"),
    }
    config = load_config()
    if budget:
        config.tasks["budget"] = {**config.tasks.get("budget", {}), **budget}
    ts = TaskStore(store, home / "data" / "tasks")
    runner = TaskRunner(config, home, home / "data" / "jarvis.db", store, ts, AuditLog(home / "data" / "audit.jsonl"),
                        lambda d: providers[d.route], provider_override="fake",
                        web=WebClient(transport=_transport, check_url=lambda u: None), **kw)
    return runner, ts, providers


def test_team_task_completes_with_receipt_and_project_output(env):
    home, _ = env
    ProjectStore(home).create("laptop", "buy a laptop")
    runner, ts, providers = _runner(env, PLAN_TEAM)
    t = ts.create("Compare 3 laptops under Rs 80,000", project="laptop")
    done = runner.run(t.id)
    assert done.state == "COMPLETED", done.last_error
    assert len(providers["researcher"].requests) == 4  # 2 researchers x 2 steps, in parallel
    report = home / "data" / "tasks" / t.id / "laptop-compare.md"
    assert report.exists() and (home / "projects" / "laptop" / "outputs" / "laptop-compare.md").exists()
    assert (home / "data" / "tasks" / t.id / "research-1.md").exists()
    receipt = (home / "data" / "tasks" / t.id / "receipt.md").read_text(encoding="utf-8")
    assert receipt.startswith(f"COMPLETED · {t.id}")
    assert "Compared laptops." in receipt
    assert "researcher-1: web_search x1" in receipt and "writer: write_file x1" in receipt
    assert "[x] every link in the report came from the research" in receipt
    assert "round 1: PASS" in receipt and "subscription, not billed per call" in receipt
    states = [e["detail"]["to"] for e in ts.events(t.id) if e["kind"] == "state"]
    assert states == ["PLANNED", "RUNNING", "VERIFYING", "COMPLETED"]


def test_ungrounded_link_triggers_one_revision(env):
    writer = RoleFake("writer", report_text=[
        "# Compare\nLaptop A Rs 75,000 https://made-up.example/x\nRecommendation: A.",
        f"# Compare\nLaptop A Rs 75,000 {SRC}\nRecommendation: A."])
    runner, ts, _ = _runner(env, PLAN_TEAM, roles={"writer": writer})
    t = ts.create("Compare laptops")
    assert runner.run(t.id).state == "COMPLETED"
    verifies = [e["detail"] for e in ts.events(t.id) if e["kind"] == "verify"]
    assert [v["passed"] for v in verifies] == [False, True]
    assert "made-up.example" in verifies[0]["problems"][0]
    assert ts.get(t.id).checkpoint["report"] == "laptop-compare-v2.md"
    # Before the rewrite, a follow-up researcher looked up what the checker found missing.
    assert (env[0] / "data" / "tasks" / t.id / "research-fix-1.md").exists()
    assert len(ts.get(t.id).checkpoint["research"]) == 3


def test_checker_rejects_twice_fails(env):
    bad = {"passed": False, "checks": [{"criterion": "3 laptops", "passed": False}], "problems": ["only 1 laptop"]}
    runner, ts, _ = _runner(env, PLAN_TEAM, roles={"checker": RoleFake("checker", verdicts=[bad])})
    t = ts.create("Compare laptops")
    done = runner.run(t.id)
    assert done.state == "FAILED" and "only 1 laptop" in done.last_error
    receipt = (env[0] / "data" / "tasks" / t.id / "receipt.md").read_text(encoding="utf-8")
    assert receipt.startswith("FAILED") and "problem: only 1 laptop" in receipt


def test_budget_stops_task(env):
    runner, ts, _ = _runner(env, PLAN_TEAM, budget={"max_model_calls": 3})
    t = ts.create("Compare laptops")
    done = runner.run(t.id)
    assert done.state == "FAILED" and "budget" in done.last_error


def test_emergency_stop_pauses_and_resume_skips_finished_stages(env):
    home, _ = env
    runner, ts, providers = _runner(env, PLAN_TEAM)
    t = ts.create("Compare laptops")
    StopSwitch(home / "data").engage("test")
    assert runner.run(t.id).state == "BACKLOG"  # stopped before anything started
    StopSwitch(home / "data").release()
    # Simulate a crash after research: checkpoint has research, state RUNNING.
    ts.set_state(t.id, "PLANNED")
    ts.update(t.id, plan=PLAN_TEAM, checkpoint={"research": [f"FINDINGS: A {SRC}"]})
    runner2, _, providers2 = _runner(env, PLAN_TEAM)
    assert runner2.run(t.id).state == "COMPLETED"
    assert providers2["researcher"].requests == []  # research was not repeated


def test_solo_task(env):
    runner, ts, providers = _runner(env, PLAN_SOLO)
    t = ts.create("Which laptop should I buy?")
    done = runner.run(t.id)
    assert done.state == "COMPLETED", done.last_error
    assert (env[0] / "data" / "tasks" / t.id / "laptop-compare.md").read_text(encoding="utf-8").startswith("Laptop A")


def test_invalid_plan_falls_back_to_solo(env):
    runner, ts, _ = _runner(env, {"nonsense": True})
    t = ts.create("Something small")
    runner.run(t.id)
    assert any(e["kind"] == "plan_fallback" for e in ts.events(t.id))


def test_worker_profile_selects_model():
    from jarvis.agents.orchestrator import TaskRunner

    cfg = load_config()
    r = TaskRunner(cfg, None, None, None, None, None, lambda d: None, workers="sonnet")
    assert r.decision_for("researcher").model == "claude-sonnet-5-5"
    assert r.decision_for("checker").model == "claude-opus-5-5"  # checker never weaker
    with pytest.raises(ValueError):
        TaskRunner(cfg, None, None, None, None, None, lambda d: None, workers="nope").decision_for("writer")


def test_state_machine(env):
    _, store = env
    ts = TaskStore(store, env[0] / "data" / "tasks")
    t = ts.create("x")
    with pytest.raises(TransitionError):
        ts.set_state(t.id, "COMPLETED")  # never without verification
    ts.set_state(t.id, "CANCELLED")
    with pytest.raises(TransitionError):
        ts.set_state(t.id, "RUNNING")
