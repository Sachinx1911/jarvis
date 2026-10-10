"""Jarvis-owned agent loop (PLAN.md section 15).

Call the provider, run tool calls through the tool registry, append results, repeat
until the model answers or the step limit is hit. The emergency stop is checked before
every provider call and every tool call. P3 secrets are redacted from every outbound
payload.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from jarvis.control.audit import AuditLog
from jarvis.control.stop import StopSwitch
from jarvis.db import Store
from jarvis.privacy import redact_p3
from jarvis.providers.base import LLMRequest, LLMResponse, Message, ReasoningProvider, TextPart, ToolResult
from jarvis.routing.policy import RouteDecision
from jarvis.tools.registry import ToolRegistry

MAX_STEPS = 6


@dataclass
class LoopResult:
    text: str
    steps: int
    stop_reason: str


def _redact_messages(messages: list[Message]) -> tuple[list[Message], int]:
    out, total = [], 0
    for m in messages:
        parts, found = [], 0
        for p in m.parts:
            if isinstance(p, TextPart):
                text, n = redact_p3(p.text)
                found += n
                parts.append(TextPart(text))
            elif isinstance(p, ToolResult):
                text, n = redact_p3(p.content)
                found += n
                parts.append(replace(p, content=text))
            else:
                parts.append(p)
        # A redacted turn must not be replayed from provider state.
        out.append(Message(m.role, parts, None if found else m.adapter_state))
        total += found
    return out, total


class AgentLoop:
    def __init__(self, provider: ReasoningProvider, decision: RouteDecision, tools: ToolRegistry,
                 store: Store, audit: AuditLog, stop: StopSwitch, max_steps: int = MAX_STEPS):
        self.provider = provider
        self.decision = decision
        self.tools = tools
        self.store = store
        self.audit = audit
        self.stop = stop
        self.max_steps = max_steps

    def run(self, history: list[Message], system: str, session_id: str) -> LoopResult:
        for step in range(1, self.max_steps + 1):
            self.stop.check()
            messages, redacted = _redact_messages(history)
            system_out, n = redact_p3(system)
            if redacted + n:
                self.audit.write("p3_redacted", session_id=session_id, count=redacted + n)
            req = LLMRequest(
                route=self.decision.route, model=self.decision.model, messages=messages,
                system=system_out, tools=self.tools.specs(),
                reasoning=self.decision.effort,  # type: ignore[arg-type]
            )
            resp = self.provider.generate(req)
            self._record(resp, session_id)
            assistant = resp.to_message()
            history.append(assistant)
            self.store.add_message(session_id, assistant)

            if resp.stop_reason == "refusal":
                return LoopResult("(The model declined this request.)", step, "refusal")
            if not resp.tool_calls:
                return LoopResult(resp.text, step, resp.stop_reason)

            results = []
            for call in resp.tool_calls:
                self.stop.check()
                results.append(self.tools.execute(call, task_id=session_id))
            tool_msg = Message("tool", list(results))
            history.append(tool_msg)
            self.store.add_message(session_id, tool_msg)

        self.audit.write("step_limit", session_id=session_id, steps=self.max_steps)
        return LoopResult("I stopped after too many steps, sir. Please try a simpler request.", self.max_steps, "step_limit")

    def _record(self, resp: LLMResponse, session_id: str) -> None:
        self.store.record_usage(session_id, self.decision.route, resp)
        self.audit.write(
            "model_call", session_id=session_id, route=self.decision.route, provider=resp.provider,
            model=resp.model, stop_reason=resp.stop_reason, input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens, cost_usd=resp.cost_usd, latency_ms=resp.latency_ms,
            tool_calls=[c.name for c in resp.tool_calls],
        )
