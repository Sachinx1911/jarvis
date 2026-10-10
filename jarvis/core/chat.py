"""Phase 0 chat session: one route, no tools, no memory yet."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Callable

from jarvis.config import Config
from jarvis.control.audit import AuditLog
from jarvis.db import Store
from jarvis.paths import PROMPTS_DIR
from jarvis.providers.base import LLMRequest, Message, ProviderError, ReasoningProvider
from jarvis.routing.policy import RouteDecision

ROUTE = "main_chat"


def system_prompt(now: datetime) -> str:
    template = (PROMPTS_DIR / "jarvis_system.md").read_text(encoding="utf-8")
    return template.replace("{local_time}", now.strftime("%Y-%m-%d %H:%M"))


class ChatSession:
    def __init__(
        self,
        config: Config,
        provider: ReasoningProvider,
        decision: RouteDecision,
        store: Store,
        audit: AuditLog,
        now: Callable[[], datetime] = datetime.now,
    ):
        self.config = config
        self.provider = provider
        self.decision = decision
        self.store = store
        self.audit = audit
        self.now = now
        self.session_id = uuid.uuid4().hex[:12]
        self.history: list[Message] = []
        audit.write(
            "route_decision", session_id=self.session_id, route=decision.route,
            provider=decision.provider, model=decision.model, reason=decision.reason,
        )

    def send(self, text: str) -> str:
        user = Message.text("user", text)
        self.history.append(user)
        self.store.add_message(self.session_id, user)

        req = LLMRequest(
            route=self.decision.route,
            model=self.decision.model,
            messages=list(self.history),
            system=system_prompt(self.now()),
            reasoning=self.decision.effort,  # type: ignore[arg-type]
        )
        try:
            resp = self.provider.generate(req)
        except ProviderError as e:
            self.history.pop()
            self.audit.write("provider_error", session_id=self.session_id, provider=self.decision.provider,
                             kind=e.kind, retryable=e.retryable, detail=str(e))
            raise

        assistant = resp.to_message()
        self.history.append(assistant)
        self.store.add_message(self.session_id, assistant)
        self.store.record_usage(self.session_id, self.decision.route, resp)
        self.audit.write(
            "model_call", session_id=self.session_id, route=self.decision.route,
            provider=resp.provider, model=resp.model, stop_reason=resp.stop_reason,
            input_tokens=resp.usage.input_tokens, output_tokens=resp.usage.output_tokens,
            cost_usd=resp.cost_usd, latency_ms=resp.latency_ms,
        )
        if resp.stop_reason == "refusal":
            return "(The model declined this request.)"
        return resp.text
