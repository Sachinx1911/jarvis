"""Agent team members as sub-loops of the Jarvis orchestrator (PLAN.md section 9).

Each agent gets its own system prompt, a fixed work order, a tool allowlist, its own route
(provider and model from the routing policy) and a step limit. Workers never ask the user:
they have no approver, so anything above T1 is refused. Agents return short summaries.

Taint travels between agents (prompt-injection defense): an agent whose input is derived from
web text (the writer gets the researchers' findings, the checker reads the report) starts
with a tainted registry, so it cannot be steered into T1 actions without approval and its
links are egress-checked. The orchestrator can also mark any hand-off tainted with
AgentEnv.tainted_input. Writers still work: write_file, create_docx and create_xlsx into the
task folder are "sandboxed" (the path policy confines them there) and every file they write is
recorded as tainted provenance, so whoever reads it later is tainted too.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable

from jarvis.config import Config
from jarvis.control.audit import AuditLog
from jarvis.control.stop import StopSwitch
from jarvis.core.loop import AgentLoop, LoopResult
from jarvis.db import Store
from jarvis.memory.store import MemoryStore
from jarvis.paths import PROMPTS_DIR
from jarvis.providers.base import Message, ReasoningProvider
from jarvis.routing.policy import RouteDecision
from jarvis.secrets import get_secret
from jarvis.tools.catalog import ToolDeps, build_registry
from jarvis.tools.quarantine import Quarantine
from jarvis.tools.registry import ToolRegistry
from jarvis.tools.system import SystemTools
from jarvis.tools.web import WebClient


@dataclass(frozen=True)
class AgentSpec:
    role: str            # researcher | writer | checker
    route: str
    prompt_file: str
    tools: frozenset[str]
    files_root: str = "workspace"  # "task" = the task folder only
    starts_tainted: bool = False   # its input is derived from untrusted (web) text
    # Set when the agent is a member of a team file (PLAN.md 27.4, the sabha): the member's name,
    # its one-line brief (appended to the role prompt) and its worker model profile (config/tasks.yaml).
    label: str = ""
    brief: str = ""
    profile: str = ""


def member_spec(base: AgentSpec, member) -> AgentSpec:
    """A team member as an AgentSpec: the role's spec, narrowed by the member's tool subset (never
    widened: the intersection with the role's allowlist), with its brief and profile. `member` is a
    jarvis.workspaces.model.Member (duck-typed to keep this module free of the workspaces package)."""
    tools = base.tools & frozenset(member.tools) if member.tools else base.tools
    return replace(base, tools=tools, label=member.name, brief=member.brief or "", profile=member.profile or "")


def assert_independent_checker(writer: AgentSpec, checker: AgentSpec) -> None:
    """Karma-yoga (PLAN.md 27.10): no agent grades its own work. The checker is never the writer (not the
    same spec, not the same team member) and can write nothing the writer could have written."""
    if writer is checker or (writer.label and writer.label == checker.label):
        raise RuntimeError("law: the checker must not be the same agent as the writer")
    if checker.role != "checker":
        raise RuntimeError(f"law: the verdict must come from a checker, not a {checker.role}")
    if checker.tools & SANDBOXED_WRITES:
        raise RuntimeError("law: the checker may not hold writing tools")


RESEARCHER = AgentSpec("researcher", "researcher", "researcher.md",
                       frozenset({"web_search", "web_fetch", "web_extract", "memory_search", "doc_search"}))
WRITER = AgentSpec("writer", "writer", "writer.md",
                   frozenset({"write_file", "read_file", "list_folder", "create_docx", "create_xlsx", "analyze_table"}),
                   "task", starts_tainted=True)
CHECKER = AgentSpec("checker", "checker", "checker.md", frozenset({"read_file", "list_folder", "web_fetch"}), "task",
                    starts_tainted=True)
# T1 new-file writes allowed while tainted, task folder only (agents whose files_root is "task")
SANDBOXED_WRITES = frozenset({"write_file", "create_docx", "create_xlsx"})


def prepare_taint(registry: ToolRegistry, spec: AgentSpec, order: "WorkOrder", env: "AgentEnv", name: str) -> None:
    """Start the agent's registry tainted when its input is untrusted; set its trusted words."""
    registry.trusted_text = lambda: [order.objective, env.goal]
    if spec.files_root == "task":
        registry.sandboxed = SANDBOXED_WRITES
    if spec.starts_tainted or env.tainted_input:
        registry.taint("agent input derived from untrusted text", agent=name, task_id=env.task_id)


@dataclass
class WorkOrder:
    """Fixed work-order format (PLAN.md 9.4): unclear specs are the top cause of team failures."""
    objective: str
    context: str = ""
    output_format: str = ""
    stop_condition: str = ""
    extra: list[str] = field(default_factory=list)

    def render(self) -> str:
        parts = [f"OBJECTIVE:\n{self.objective}"]
        if self.context:
            parts.append(f"CONTEXT:\n{self.context}")
        if self.output_format:
            parts.append(f"OUTPUT:\n{self.output_format}")
        if self.stop_condition:
            parts.append(f"STOP WHEN:\n{self.stop_condition}")
        parts.extend(self.extra)
        return "\n\n".join(parts)


@dataclass
class AgentEnv:
    """What an agent needs to run. Each thread opens its own SQLite connection."""
    config: Config
    home: Path
    db_path: Path
    audit: AuditLog
    stop: StopSwitch
    task_id: str
    task_dir: Path
    provider_for: Callable[[RouteDecision], ReasoningProvider]
    decision_for: Callable[[str], RouteDecision]
    quarantine_for: Callable[[], Quarantine | None]
    on_usage: Callable | None = None
    web: WebClient | None = None
    max_steps: int = 8
    tainted_input: bool = False  # the orchestrator hands this agent untrusted (web-derived) text
    goal: str = ""               # the user's own task goal (trusted words for the egress policy)
    workspace: str = "personal"  # the task's office: memory in view and usage records (PLAN.md 18.2 step 0)
    share_personal: bool = True


def run_agent(spec: AgentSpec, name: str, order: WorkOrder, env: AgentEnv) -> LoopResult:
    store = Store(env.db_path)
    try:
        decision = env.decision_for(spec.route, spec.profile) if spec.profile else env.decision_for(spec.route)
        tools_config = dict(env.config.tools)
        if spec.files_root == "task":
            tools_config["files"] = {"allowed": [str(env.task_dir)]}
        registry = ToolRegistry(store, env.audit)  # no approver: workers never ask the user
        from jarvis.control.fence import fence_for
        registry.set_fence(fence_for(env.home, env.workspace), env.workspace)   # the office's fence (27.3)
        build_registry(registry, ToolDeps(
            home=env.home, store=store, audit=env.audit, memory=MemoryStore(env.home, store), skills=None,
            session_id=lambda: name, max_privacy="P1", tools_config=tools_config,
            web=env.web or WebClient(), quarantine=env.quarantine_for(),
            tavily_key=lambda: get_secret("tavily_api_key"), system=SystemTools(),
            workspace=env.workspace, share_personal=env.share_personal,
        ))
        registry.restrict(set(spec.tools))
        prepare_taint(registry, spec, order, env, name)
        for tool in registry.all():  # workers stay at T0/T1 whatever the registry file says
            if tool.tier not in ("T0", "T1"):
                registry.register(replace(tool, enabled=False))
        loop = AgentLoop(env.provider_for(decision), decision, registry, store, env.audit, env.stop,
                         max_steps=env.max_steps, task_id=env.task_id, on_usage=env.on_usage, agent=name)
        loop.workspace = env.workspace
        system = (PROMPTS_DIR / spec.prompt_file).read_text(encoding="utf-8")
        if spec.brief:
            system += f"\n\nYour brief (you are {spec.label or spec.role} on this team): {spec.brief}"
        history = [Message.text("user", order.render())]
        env.audit.write("agent_start", task_id=env.task_id, agent=name, route=spec.route, model=decision.model,
                        **({"member": spec.label} if spec.label else {}))
        result = loop.run(history, system, f"{env.task_id}-{name}-{uuid.uuid4().hex[:4]}")
        env.audit.write("agent_end", task_id=env.task_id, agent=name, steps=result.steps, stop=result.stop_reason)
        return result
    finally:
        store.close()
