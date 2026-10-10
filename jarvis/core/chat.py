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
from jarvis.control.approvals import ApprovalGate, Approver
from jarvis.providers.base import Message, ProviderError, ReasoningProvider
from jarvis.routing.policy import RouteDecision
from jarvis.secrets import get_secret
from jarvis.skills.loader import SkillLibrary
from jarvis.tools.catalog import ToolDeps, apply_registry, build_registry, registry_path
from jarvis.tools.quarantine import Quarantine
from jarvis.tools.registry import ToolRegistry
from jarvis.tools.system import SystemTools
from jarvis.tools.web import WebClient

ROUTE = "main_chat"


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
        approver: Approver | None = None,
        quarantine: Quarantine | None = None,
        web: WebClient | None = None,
        system: SystemTools | None = None,
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
        self.approver_for_tasks = approver
        max_privacy = config.routing.get("routes", {}).get(decision.route, {}).get("max_privacy", "P1")
        from jarvis.connectors.registry import ConnectorDeps, doc_library
        self.context = ContextBuilder(home, memory, skills, max_privacy,
                                      docs=doc_library(ConnectorDeps(home, store, audit, max_privacy)))
        self.stop = StopSwitch(home / "data")
        self.tools = ToolRegistry(store, audit, ApprovalGate(store, audit, approver))
        build_registry(self.tools, ToolDeps(
            home=home, store=store, audit=audit, memory=memory, skills=skills,
            session_id=lambda: self.session_id, max_privacy=max_privacy, tools_config=config.tools,
            web=web or WebClient(), quarantine=quarantine, tavily_key=lambda: get_secret("tavily_api_key"),
            system=system or SystemTools(),
        ))
        apply_registry(self.tools, registry_path(home), audit)
        from jarvis.connectors.registry import apply_connector_registry
        apply_connector_registry(self.tools, registry_path(home), audit)
        self.loop = AgentLoop(provider, decision, self.tools, store, audit, self.stop)
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
