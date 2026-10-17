"""Phase 8 agents: Operator and Coder (PLAN.md 9.1), plus the extra tools they use.

Operator: apps, files and the isolated browser, per safety tiers. It never asks the user
itself: T2/T3 actions go through Jarvis's approval gate (the approver Jarvis passes in), and
with no approver they are refused. Coder: typed code tools in its own project folder only
(<home>/workspace/code/<project>/), no raw shell, T0/T1 only.

The registry is built the same way as jarvis/agents/team.run_agent, plus extra_tools().
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from pathlib import Path

from jarvis.agents.team import AgentEnv, AgentSpec, WorkOrder, prepare_taint
from jarvis.browser.recording import active_recording_dir, STEPS_FILE
from jarvis.browser.session import BrowserSession
from jarvis.browser.tools import browser_tools
from jarvis.control.approvals import ApprovalGate, ApprovalRequest, Approver
from jarvis.core.loop import AgentLoop, LoopResult
from jarvis.db import Store
from jarvis.memory.store import MemoryStore
from jarvis.paths import PROMPTS_DIR
from jarvis.providers.base import Message
from jarvis.secrets import get_secret
from jarvis.tools.catalog import ToolDeps, apply_registry, build_registry, registry_path
from jarvis.tools.code import CodeTools, ProcessRunner, coder_tools, load_coder_config, project_root
from jarvis.tools.registry import Tool, ToolRegistry
from jarvis.tools.system import SystemTools
from jarvis.tools.web import WebClient

BROWSER_TOOLS = frozenset({"browser_open", "browser_read", "browser_click", "browser_fill", "browser_submit",
                           "browser_screenshot", "browser_download"})
CODER_TOOLS = frozenset({"code_read", "code_write", "run_tests"})

OPERATOR = AgentSpec("operator", "operator", "operator.md",
                     BROWSER_TOOLS | {"read_file", "list_folder", "write_file", "open_app", "notify", "web_fetch"},
                     "task")
CODER = AgentSpec("coder", "coder", "coder.md", CODER_TOOLS)


def open_browser_session(home: Path, task_dir: Path, allowed_domains: list[str], audit=None, site: str | None = None,
                         **kw) -> BrowserSession:
    """A browser session for one task. While a teach-by-demonstration recording runs, its steps
    are also written into the recording folder (browser_steps_evidence reads them)."""
    sinks = list(kw.pop("step_sinks", []))
    rec = active_recording_dir(home)
    if rec is not None:
        sinks.append(rec / STEPS_FILE)
    return BrowserSession(home, task_dir, allowed_domains, audit=audit, site=site, step_sinks=sinks, **kw)


def extra_tools(deps: ToolDeps, browser: BrowserSession | None = None, coder_project: str | None = None,
                process_runner: ProcessRunner | None = None, coder_config: dict | None = None) -> list[Tool]:
    """Phase 8 tools to merge into a registry built by catalog.build_registry:
    browser tools when a session is given (its allowlist is fixed already), code tools when a
    Coder project is given."""
    tools: list[Tool] = []
    if browser is not None:
        tools += browser_tools(browser, deps.quarantine)
    if coder_project:
        cfg = coder_config if coder_config is not None else load_coder_config()
        tools += coder_tools(CodeTools(project_root(deps.home, coder_project, cfg), cfg, process_runner))
    return tools


def _via_jarvis(approver: Approver, agent: str) -> Approver:
    """The agent never talks to the user; Jarvis shows the request and says which agent wants it."""
    def ask(req: ApprovalRequest) -> bool:
        return bool(approver(replace(req, reason=f"{req.reason}; requested by the {agent} agent")))
    return ask


def run_extra_agent(spec: AgentSpec, name: str, order: WorkOrder, env: AgentEnv, *, approver: Approver | None = None,
                    browser: BrowserSession | None = None, coder_project: str | None = None,
                    process_runner: ProcessRunner | None = None, coder_config: dict | None = None) -> LoopResult:
    store = Store(env.db_path)
    try:
        decision = env.decision_for(spec.route)
        tools_config = dict(env.config.tools)
        if spec.files_root == "task":
            tools_config["files"] = {"allowed": [str(env.task_dir)]}
        # Only the Operator may reach Jarvis's approver; the Coder (and any worker) has none.
        gate_approver = _via_jarvis(approver, name) if approver and spec.role == "operator" else None
        registry = ToolRegistry(store, env.audit, ApprovalGate(store, env.audit, gate_approver))
        deps = ToolDeps(
            home=env.home, store=store, audit=env.audit, memory=MemoryStore(env.home, store), skills=None,
            session_id=lambda: name, max_privacy="P1", tools_config=tools_config,
            web=env.web or WebClient(), quarantine=env.quarantine_for(),
            tavily_key=lambda: get_secret("tavily_api_key"), system=SystemTools(),
            workspace=env.workspace, share_personal=env.share_personal,
        )
        build_registry(registry, deps)
        for tool in extra_tools(deps, browser, coder_project, process_runner, coder_config):
            registry.register(tool)
        apply_registry(registry, registry_path(env.home), env.audit)  # disable / raise tiers only
        registry.restrict(set(spec.tools))
        prepare_taint(registry, spec, order, env, name)
        if spec.role != "operator":  # the Coder stays at T0/T1 whatever the registry file says
            for tool in registry.all():
                if tool.tier not in ("T0", "T1"):
                    registry.register(replace(tool, enabled=False))
        loop = AgentLoop(env.provider_for(decision), decision, registry, store, env.audit, env.stop,
                         max_steps=env.max_steps, task_id=env.task_id, on_usage=env.on_usage, agent=name)
        loop.workspace = env.workspace
        system = (PROMPTS_DIR / spec.prompt_file).read_text(encoding="utf-8")
        env.audit.write("agent_start", task_id=env.task_id, agent=name, route=spec.route, model=decision.model)
        result = loop.run([Message.text("user", order.render())], system, f"{env.task_id}-{name}-{uuid.uuid4().hex[:4]}")
        env.audit.write("agent_end", task_id=env.task_id, agent=name, steps=result.steps, stop=result.stop_reason)
        return result
    finally:
        if browser is not None:
            browser.close()  # end of the agent's work: the fresh context is wiped
        store.close()
