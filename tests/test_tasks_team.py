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
from jarvis.tools.web import TAVILY_EXTRACT_URL, WebClient

SRC = "https://www.smartprix.com/laptops/example-laptop-a"  # aggregator: estimate
AMZ = "https://www.amazon.in/dp/B0EXAMPLE1"  # check yourself
STORE = "https://www.croma.com/example-laptop-b/p/100002"  # official store page
ROW_A = f"| Laptop A | Rs 75,000 | estimate (aggregator) | {SRC} | check yourself: {AMZ} |"


class RoleFake(FakeProvider):
    """Stateless per-agent behaviour, safe for parallel researchers."""

    def __init__(self, role, report_text=None, verdicts=None):
        super().__init__()
        self.role = role
        self.report_text = report_text or [f"# Compare\n{ROW_A}\nRecommendation: Laptop A."]
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
                text = (f"FINDINGS:\n- Laptop A Rs 75,000 estimate (aggregator)\nSOURCES:\n- Smartprix - {SRC}\n"
                        f"- Amazon - {AMZ}\nGAPS: none")
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


STORE_PAGE = "# Laptop B 14\nMenu Filters\nLaptop B 14 (i5, 16GB)\nOffer price: \u20b972,490\n"


def _transport(method, url, headers, body):
    if url == TAVILY_EXTRACT_URL:
        target = json.loads(body)["urls"][0]
        return 200, json.dumps({"results": [{"url": target, "raw_content": STORE_PAGE}], "failed_results": []}).encode()
    return 200, json.dumps({"results": [{"title": "Smartprix", "url": SRC, "content": "Laptop A Rs 75,000"},
                                        {"title": "Amazon", "url": AMZ, "content": "Laptop A"},
                                        {"title": "Croma", "url": STORE, "content": "Laptop B 14"}]}).encode()


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
        "operator": roles.get("operator") or FakeProvider(),
        "coder": roles.get("coder") or FakeProvider(),
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
    # law 3: the finished task left an episode in its office's memory
    from jarvis.memory.store import MemoryStore
    episodes = [m for m in MemoryStore(home, runner.store).list(type="episode")]
    assert len(episodes) == 1 and episodes[0].workspace == "personal" and episodes[0].source == "observed"
    assert "Compared laptops." in episodes[0].body and t.id in episodes[0].name
    assert "receipt_remembered" in (home / "data" / "audit.jsonl").read_text(encoding="utf-8")


def test_ungrounded_link_triggers_one_revision(env):
    writer = RoleFake("writer", report_text=[
        "# Compare\nLaptop A Rs 75,000 https://made-up.example/x\nRecommendation: A.",
        f"# Compare\n{ROW_A}\nRecommendation: A."])
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
    ts.update(t.id, plan=PLAN_TEAM, checkpoint={"research": [f"FINDINGS: A {SRC} {AMZ}"]})
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


def test_cancel_while_running_stops_at_next_step(env):
    home, _ = env

    class CancellingResearcher(RoleFake):
        def generate(self, req):
            # Sachin cancels from another window while the researcher works.
            from jarvis.tasks.store import TaskStore
            store = Store(home / "data" / "jarvis.db")
            ts2 = TaskStore(store, home / "data" / "tasks")
            if ts2.get("t-001").state != "CANCELLED":  # two researchers run in parallel; cancel once
                try:
                    ts2.set_state("t-001", "CANCELLED", "user cancelled")
                except Exception:  # the other researcher won the race
                    pass
            store.close()
            return super().generate(req)

    runner, ts, providers = _runner(env, PLAN_TEAM, roles={"researcher": CancellingResearcher("researcher")})
    t = ts.create("Compare laptops")
    done = runner.run(t.id)
    assert done.state == "CANCELLED"
    assert providers["writer"].requests == []  # nothing after the cancel
    assert (home / "data" / "tasks" / t.id / "receipt.md").read_text(encoding="utf-8").startswith("CANCELLED")
    assert runner.run(t.id).state == "CANCELLED"  # a cancelled task never restarts


def test_operate_mode_runs_operator_and_checker(env):
    plan = {**PLAN_SOLO, "mode": "operate", "deliverable": {"filename": "done.md", "outline": "what was done"}}
    runner, ts, providers = _runner(env, plan, roles={"operator": FakeProvider(script=[
        {"tool": "write_file", "arguments": {"path": "todo.txt", "content": "buy milk"}},
        "DONE:\n- Created todo.txt\nEVIDENCE: todo.txt\nNOT DONE: none"])})
    t = ts.create("Make a todo file for me")
    done = runner.run(t.id)
    assert done.state == "COMPLETED", done.last_error
    assert "Created todo.txt" in (env[0] / "data" / "tasks" / t.id / "done.md").read_text(encoding="utf-8")


def test_operate_mode_fails_when_the_claimed_action_never_ran(env):
    """Verify-after-act: the old silent failure ("Opened notepad" with no tool run) now fails."""
    plan = {**PLAN_SOLO, "mode": "operate", "deliverable": {"filename": "done.md", "outline": "what was done"}}
    runner, ts, _ = _runner(env, plan, roles={"operator": FakeProvider(script=["Opened notepad and checked it runs."])})
    t = ts.create("Open notepad for me")
    done = runner.run(t.id)
    assert done.state == "FAILED" and "claimed but not done" in done.last_error


def test_code_mode_fails_without_passing_tests(env):
    plan = {**PLAN_SOLO, "mode": "code", "deliverable": {"filename": "code.md", "outline": "summary"}}
    runner, ts, _ = _runner(env, plan, roles={"coder": FakeProvider(script=["Wrote the function."])})
    t = ts.create("Write a hello function")
    done = runner.run(t.id)
    assert done.state == "FAILED" and "tests were not run" in done.last_error


# ---- source tiers for prices (confirmed store page / labelled estimate / check yourself) ----

class PriceResearcher(RoleFake):
    """Searches, reads the Croma page with web_extract, then reports both laptops."""

    def generate(self, req):
        self.requests.append(req)
        tools_done = sum(1 for m in req.messages if m.role == "tool")
        if tools_done == 0:
            calls = [ToolCall("s1", "web_search", {"query": "laptops under 80000"})]
        elif tools_done == 1:
            calls = [ToolCall("e1", "web_extract", {"url": STORE, "question": "price?", "product": "Laptop B 14"})]
        else:
            calls = []
        text = "" if calls else (f"FINDINGS:\n- Laptop A estimate (aggregator) Rs 75,000 {SRC}; check yourself {AMZ}\n"
                                 f"- Laptop B confirmed (store page) Rs 72,490 {STORE}\nGAPS: none")
        return LLMResponse(text, calls, "tool_use" if calls else "end", Usage(1000, 200), "fake", req.model, 0,
                           cost_usd=None, adapter_state={"notional_usd": 0.01})


@pytest.fixture
def with_extract(monkeypatch):
    """Register web_extract next to the catalog tools (the lead wires it into the catalog)."""
    from jarvis.tools import catalog
    from jarvis.tools.extract_tool import make_web_extract_tool

    def build(reg, deps):
        catalog.build_registry(reg, deps)
        reg.register(make_web_extract_tool(deps))
        return reg

    monkeypatch.setattr("jarvis.agents.team.build_registry", build)


def _price_report(b_label):
    from jarvis.agents.sources import today
    return (f"# Compare\n| Laptop | Price | Price status | Links |\n|---|---|---|---|\n{ROW_A}\n"
            f"| Laptop B | Rs 72,490 | {b_label.format(day=today())} | {STORE} |\nRecommendation: Laptop B.")


def test_price_task_passes_with_confirmed_and_labelled_estimate(env, with_extract):
    writer = RoleFake("writer", report_text=[_price_report("confirmed (store page, {day})")])
    runner, ts, providers = _runner(env, PLAN_TEAM, roles={"researcher": PriceResearcher("researcher"),
                                                            "writer": writer})
    t = ts.create("Compare 3 laptops under Rs 80,000 with a source link for every price")
    done = runner.run(t.id)
    assert done.state == "COMPLETED", done.last_error
    verify = [e["detail"] for e in ts.events(t.id) if e["kind"] == "verify"][0]
    tier = [c for c in verify["checks"] if c["check"].startswith("every price row")][0]
    assert tier["passed"] and tier["note"].startswith("2 price rows")
    # Researchers, writer and checker were all told the price rules.
    assert "PRICE RULES" in providers["researcher"].requests[0].messages[0].text_content()
    assert "PRICE RULES" in providers["writer"].requests[0].messages[0].text_content()
    checker_order = providers["checker"].requests[0].messages[0].text_content()
    assert "PRICE RULES" in checker_order and "price-label check on 2 rows: passed" in checker_order


def test_price_task_fails_when_estimate_is_presented_as_confirmed(env, with_extract):
    from jarvis.agents.sources import today
    fake_confirmed = ROW_A.replace("estimate (aggregator)", f"confirmed (store page, {today()})")
    writer = RoleFake("writer", report_text=[f"# Compare\n{fake_confirmed}\nRecommendation: Laptop A."])
    runner, ts, _ = _runner(env, PLAN_TEAM, roles={"researcher": PriceResearcher("researcher"), "writer": writer})
    t = ts.create("Compare 3 laptops under Rs 80,000 with a source link for every price")
    done = runner.run(t.id)
    assert done.state == "FAILED"
    assert "says confirmed but has no official store-page link" in done.last_error


def test_store_price_without_evidence_cannot_be_confirmed(env):
    # No web_extract in this run: the Croma link came only from search results.
    writer = RoleFake("writer", report_text=[_price_report("confirmed (store page, {day})")])
    runner, ts, _ = _runner(env, PLAN_TEAM, roles={"writer": writer})
    t = ts.create("Compare 3 laptops under Rs 80,000")
    done = runner.run(t.id)
    assert done.state == "FAILED" and "never found a Rs price" in done.last_error


def test_price_check_off_for_non_price_plan(env):
    writer = RoleFake("writer", report_text=[f"# Compare\n| Laptop A | Rs 75,000 | {SRC} |\nRecommendation: A."])
    runner, ts, _ = _runner(env, {**PLAN_TEAM, "price_check": False}, roles={"writer": writer})
    t = ts.create("Compare 3 laptops under Rs 80,000")
    assert runner.run(t.id).state == "COMPLETED"