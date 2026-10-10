"""Typed tool registry: one registry for every provider; specs use the portable schema subset.

Order for every call: known and enabled tool -> argument schema -> path pre-check (secret
locations are T4) -> risk-tier gate and approval -> run -> verify -> log. The risk tier
never goes to a model. Reading untrusted content (web) taints the session.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Callable

from jarvis.control.approvals import ApprovalGate
from jarvis.control.audit import AuditLog
from jarvis.db import Store
from jarvis.providers.base import ToolCall, ToolResult, ToolSpec
from jarvis.schema import validate
from jarvis.tools.files import PathBlocked, PathDenied

TIERS = ("T0", "T1", "T2", "T3", "T4")
MAX_RESULT_CHARS = 8000


@dataclass(frozen=True)
class Tool:
    spec: ToolSpec
    tier: str
    handler: Callable[[dict], str]
    verify: Callable[[dict], tuple[bool, str]] | None = None
    precheck: Callable[[dict], None] | None = None  # raises PathBlocked / PathDenied
    taints: bool = False  # output is untrusted outside content
    enabled: bool = True


@dataclass
class ToolRegistry:
    store: Store
    audit: AuditLog
    gate: ApprovalGate | None = None
    tainted: bool = False
    _tools: dict[str, Tool] = field(default_factory=dict)

    def __post_init__(self):
        if self.gate is None:
            self.gate = ApprovalGate(self.store, self.audit)

    def register(self, tool: Tool) -> None:
        if tool.tier not in TIERS:
            raise ValueError(f"unknown tier {tool.tier}")
        self._tools[tool.spec.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def all(self) -> list[Tool]:
        return list(self._tools.values())

    def specs(self) -> list[ToolSpec]:
        return [t.spec for t in self._tools.values() if t.enabled and t.tier != "T4"]

    def restrict(self, names: set[str]) -> None:
        """Keep only these tools (agent allowlists)."""
        self._tools = {k: v for k, v in self._tools.items() if k in names}

    def execute(self, call: ToolCall, task_id: str | None = None, agent: str | None = None) -> ToolResult:
        self._agent = agent
        tool = self._tools.get(call.name)
        if tool is None or not tool.enabled:
            return self._finish(call, tool, task_id, f"unknown or disabled tool: {call.name}", "refused", False)
        if not validate(call.arguments, tool.spec.parameters):
            return self._finish(call, tool, task_id, f"invalid arguments for {call.name}", "refused", False)
        try:
            if tool.precheck:
                tool.precheck(call.arguments)
        except PathBlocked as e:
            self.audit.write("t4_attempt", tool=call.name, arguments=call.arguments, detail=str(e))
            return self._finish(call, tool, task_id, f"Blocked: {e}. This is never allowed.", "blocked_t4", False)
        except PathDenied as e:
            return self._finish(call, tool, task_id, f"Not allowed: {e}.", "refused", False)

        assert self.gate is not None
        allowed, decision = self.gate.check(call.name, tool.tier, call.arguments, self.tainted, task_id)
        if not allowed:
            return self._finish(call, tool, task_id, f"Not run: {decision}.", decision, False)

        try:
            result = tool.handler(call.arguments)
        except (PathBlocked, PathDenied) as e:
            return self._finish(call, tool, task_id, f"Not allowed: {e}.", "refused", False)
        except Exception as e:  # a failing tool must not crash the loop
            return self._finish(call, tool, task_id, f"tool error: {e}", decision, False)

        if tool.taints:
            if not self.tainted:
                self.audit.write("session_tainted", tool=call.name)
            self.tainted = True
        verified = None
        if tool.verify:
            try:
                ok, how = tool.verify(call.arguments)
            except Exception as e:
                ok, how = False, f"verifier error: {e}"
            verified = ok
            result += f"\n[verified: {how}]" if ok else f"\n[NOT verified: {how}]"
        return self._finish(call, tool, task_id, result[:MAX_RESULT_CHARS], decision, True, verified)

    def _finish(self, call: ToolCall, tool: Tool | None, task_id: str | None, content: str, decision: str,
                ok: bool, verified: bool | None = None) -> ToolResult:
        tier = tool.tier if tool else "?"
        self.store.conn.execute(
            "INSERT INTO tool_runs (task_id, tool, tier, arguments, result, ok, agent) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (task_id, call.name, tier, json.dumps(call.arguments, ensure_ascii=False), content[:4000], int(ok),
             getattr(self, "_agent", None)),
        )
        self.store.conn.commit()
        self.audit.write(
            "tool_run", tool=call.name, agent=getattr(self, "_agent", None), tier=tier, arguments=call.arguments, decision=decision, ok=ok,
            verified=verified, output_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            tainted=self.tainted,
        )
        return ToolResult(call.id, content, is_error=not ok)
