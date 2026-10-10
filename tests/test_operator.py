"""Phase 8: Operator agent with the isolated browser (fake driver). Only Jarvis asks the user."""

import pytest

from jarvis.agents.extra import OPERATOR, CODER, extra_tools, open_browser_session, run_extra_agent
from jarvis.agents.team import AgentEnv, WorkOrder
from jarvis.browser.fake import FakeDriver, FakeElement, FakePage
from jarvis.config import load_config
from jarvis.control.audit import AuditLog
from jarvis.control.stop import StopSwitch
from jarvis.db import Store
from jarvis.providers.fake import FakeProvider
from jarvis.routing.policy import decide
from jarvis.tools.catalog import ToolDeps
from jarvis.tools.system import SystemTools
from jarvis.tools.web import WebClient

CONFIG = {"default_allowed_domains": [], "downloads": {"max_mb": 1, "allowed_types": ["pdf"]}}
PAGES = {
    "https://shop.example/contact": FakePage(
        text="Contact us", form_action="https://shop.example/send", after_submit="https://shop.example/thanks",
        elements={"name": FakeElement(name="name"),
                  "Send": FakeElement(tag="button", type="submit", text="Send", submits=True)}),
    "https://shop.example/thanks": FakePage(text="Thanks"),
}
SCRIPT = [
    {"tool": "browser_open", "arguments": {"url": "https://shop.example/contact"}},
    {"tool": "browser_fill", "arguments": {"field": "name", "value": "Asha Demo"}},
    {"tool": "browser_submit", "arguments": {}},
    "DONE: sent the contact form\nEVIDENCE: browser/screenshots\nNOT DONE: none",
]


@pytest.fixture
def env(tmp_path):
    FakeDriver.instances.clear()
    store = Store(tmp_path / "data" / "jarvis.db")
    audit = AuditLog(tmp_path / "data" / "audit.jsonl")
    yield tmp_path, store, audit
    store.close()


def _run(env, approver):
    home, store, audit = env
    config = load_config()
    task_dir = home / "data" / "tasks" / "t-001"
    task_dir.mkdir(parents=True, exist_ok=True)
    provider = FakeProvider(script=list(SCRIPT))
    agent_env = AgentEnv(config, home, home / "data" / "jarvis.db", audit, StopSwitch(home / "data"), "t-001",
                         task_dir, lambda d: provider, lambda route: decide(config, route, "fake"), lambda: None,
                         web=WebClient(transport=lambda *a: (404, b""), check_url=lambda u: None), max_steps=8)
    browser = open_browser_session(home, task_dir, ["shop.example"], audit=audit, config=CONFIG,
                                   driver_factory=lambda: FakeDriver(PAGES), check_url=lambda u: None)
    result = run_extra_agent(OPERATOR, "operator", WorkOrder("Send the contact form"), agent_env,
                             approver=approver, browser=browser)
    return result, provider, task_dir


def test_operator_submit_goes_through_jarvis_approval(env):
    asked = []

    def jarvis_approver(req):
        asked.append(req)
        return True

    result, provider, task_dir = _run(env, jarvis_approver)
    assert result.text.startswith("DONE")
    tools = {t.name for t in provider.requests[0].tools}
    assert {"browser_open", "browser_submit", "read_file"} <= tools and "code_write" not in tools
    submit = [r for r in asked if r.tool == "browser_submit"]
    assert submit and submit[0].tier == "T3" and "requested by the operator agent" in submit[0].reason
    assert submit[0].arguments["form"]["name (text)"] == "Asha Demo"
    driver = FakeDriver.instances[-1]
    assert ("submit", None) in driver.actions and driver.closed  # the browser is wiped at the end
    assert list((task_dir / "browser" / "screenshots").glob("*.png"))


def test_operator_without_approver_cannot_submit(env):
    result, _, _ = _run(env, None)
    driver = FakeDriver.instances[-1]
    assert not any(a[0] in ("submit", "fill") for a in driver.actions)  # fill is T2, submit T3
    assert driver.closed


def test_extra_tools_merge(env):
    home, store, audit = env
    deps = ToolDeps(home=home, store=store, audit=audit, memory=None, skills=None, session_id=lambda: "s",
                    max_privacy="P1", tools_config={}, web=WebClient(), quarantine=None,
                    tavily_key=lambda: None, system=SystemTools())
    assert extra_tools(deps) == []
    names = [t.spec.name for t in extra_tools(deps, coder_project="demo-app",
                                              coder_config={"test_commands": ["pytest -q"]})]
    assert names == ["code_read", "code_write", "run_tests"]
    browser = open_browser_session(home, home / "data" / "tasks" / "t-9", ["shop.example"], config=CONFIG,
                                   driver_factory=lambda: FakeDriver(PAGES), check_url=lambda u: None)
    tiers = {t.spec.name: t.tier for t in extra_tools(deps, browser=browser)}
    assert tiers == {"browser_open": "T1", "browser_read": "T0", "browser_click": "T2", "browser_fill": "T2",
                     "browser_submit": "T3", "browser_screenshot": "T0", "browser_download": "T2"}
    assert CODER.tools == {"code_read", "code_write", "run_tests"}
    assert "web_fetch" in next(t.spec.description for t in extra_tools(deps, browser=browser)
                               if t.spec.name == "browser_open")  # APIs first
