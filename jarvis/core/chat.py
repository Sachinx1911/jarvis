"""Chat session: context builder + agent loop + memory commands."""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path
from typing import Callable

from jarvis.config import Config
from jarvis.control.audit import AuditLog
from jarvis.control.stop import StopSwitch
from jarvis.core.context import ContextBuilder
from jarvis.core.loop import AgentLoop
from jarvis.db import Store
from jarvis.memory.extract import Extractor
from jarvis.memory.store import MemoryStore
from jarvis.paths import default_paths
from jarvis.privacy import SENSITIVITY_TO_CLASS, allowed
from jarvis.providers.base import Message, ProviderError, ReasoningProvider
from jarvis.routing.policy import RouteDecision
from jarvis.skills.loader import SkillLibrary
from jarvis.tools.registry import Tool, ToolRegistry
from jarvis.providers.base import ToolSpec

ROUTE = "main_chat"


def build_tools(registry: ToolRegistry, memory: MemoryStore | None, skills: SkillLibrary | None,
                store: Store, session_id: Callable[[], str], max_privacy: str) -> None:
    if memory:
        def memory_search(args: dict) -> str:
            lines = []
            for hit in memory.search(args["query"], k=5):
                m = hit.memory
                if not allowed(SENSITIVITY_TO_CLASS.get(m.sensitivity, "P2"), max_privacy):
                    lines.append(f"- [{m.id}] (sensitive memory withheld)")
                    continue
                memory.mark_used(m.id)
                lines.append(f"- [{m.id}, {m.type}] {m.summary_en or m.name}: {m.body}")
            return "\n".join(lines) or "No matching memories."

        registry.register(Tool(ToolSpec(
            "memory_search", "Search the user's long-term memory. Use English keywords and the user's own words.",
            {"type": "object", "properties": {"query": {"type": "string", "description": "What to look for"}},
             "required": ["query"]},
        ), "T0", memory_search))

    def session_search(args: dict) -> str:
        rows = store.search_sessions(args["query"], limit=5, exclude_session=session_id())
        return "\n".join(f"- {r['ts']} {r['role']}: {r['text'][:300]}" for r in rows) or "No matching past conversations."

    registry.register(Tool(ToolSpec(
        "session_search", "Search past conversations with the user.",
        {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
    ), "T0", session_search))

    if skills:
        def load_skill(args: dict) -> str:
            return skills.load(args["name"]) or f"No skill named {args['name']}."

        registry.register(Tool(ToolSpec(
            "load_skill", "Load the full instructions of a skill from the skill index.",
            {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
        ), "T0", load_skill))


class ChatSession:
    def __init__(
        self,
        config: Config,
        provider: ReasoningProvider,
        decision: RouteDecision,
        store: Store,
        audit: AuditLog,
        now: Callable[[], datetime] = datetime.now,
        home: Path | None = None,
        memory: MemoryStore | None = None,
        skills: SkillLibrary | None = None,
        extractor: Extractor | None = None,
    ):
        home = home or default_paths().home
        self.config = config
        self.provider = provider
        self.decision = decision
        self.store = store
        self.audit = audit
        self.now = now
        self.memory = memory
        self.extractor = extractor
        self.session_id = uuid.uuid4().hex[:12]
        self.history: list[Message] = []
        max_privacy = config.routing.get("routes", {}).get(decision.route, {}).get("max_privacy", "P1")
        self.context = ContextBuilder(home, memory, skills, max_privacy)
        self.stop = StopSwitch(home / "data")
        tools = ToolRegistry(store, audit)
        build_tools(tools, memory, skills, store, lambda: self.session_id, max_privacy)
        self.loop = AgentLoop(provider, decision, tools, store, audit, self.stop)
        audit.write(
            "route_decision", session_id=self.session_id, route=decision.route,
            provider=decision.provider, model=decision.model, reason=decision.reason,
        )

    def send(self, text: str) -> str:
        self.stop.check()
        user = Message.text("user", text)
        self.history.append(user)
        self.store.add_message(self.session_id, user)
        ctx = self.context.build(text, self.now())
        if ctx.withheld:
            self.audit.write("privacy_withheld", session_id=self.session_id, count=ctx.withheld)
        for mid in ctx.memory_ids:
            self.memory.mark_used(mid)  # type: ignore[union-attr]
        start = len(self.history)
        try:
            result = self.loop.run(self.history, ctx.system, self.session_id)
        except ProviderError as e:
            del self.history[start - 1:]  # drop the unanswered user turn and partial steps
            self.audit.write("provider_error", session_id=self.session_id, provider=self.decision.provider,
                             kind=e.kind, retryable=e.retryable, detail=str(e))
            raise
        return result.text

    def user_messages(self) -> list[str]:
        return [m.text_content() for m in self.history if m.role == "user"]

    def end(self) -> list[tuple[str, str]]:
        """Session over: extract memories from what the user said (PLAN.md 6.3)."""
        if not self.extractor or not self.user_messages():
            return []
        results = self.extractor.extract_session(self.user_messages())
        self.audit.write("session_extracted", session_id=self.session_id, results=results)
        return results
