"""Typed tool registry. One registry for every provider; specs use the portable schema subset.

Phase 1 runs only T0 (read-only) tools. Higher tiers need the approval system (Phase 2)
and are refused here. The risk tier never goes to a model.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable

from jarvis.control.audit import AuditLog
from jarvis.db import Store
from jarvis.providers.base import ToolCall, ToolResult, ToolSpec
from jarvis.schema import validate

TIERS = ("T0", "T1", "T2", "T3", "T4")
MAX_RESULT_CHARS = 8000


@dataclass(frozen=True)
class Tool:
    spec: ToolSpec
    tier: str
    handler: Callable[[dict], str]


class ToolRegistry:
    def __init__(self, store: Store, audit: AuditLog, allowed_tiers: tuple[str, ...] = ("T0",)):
        self._tools: dict[str, Tool] = {}
        self.store = store
        self.audit = audit
        self.allowed_tiers = allowed_tiers

    def register(self, tool: Tool) -> None:
        if tool.tier not in TIERS:
            raise ValueError(f"unknown tier {tool.tier}")
        self._tools[tool.spec.name] = tool

    def specs(self) -> list[ToolSpec]:
        return [t.spec for t in self._tools.values()]

    def execute(self, call: ToolCall, task_id: str | None = None) -> ToolResult:
        tool = self._tools.get(call.name)
        if tool is None:
            return self._finish(call, None, task_id, f"unknown tool: {call.name}", ok=False)
        if tool.tier == "T4" or tool.tier not in self.allowed_tiers:
            self.audit.write("tool_blocked", tool=call.name, tier=tool.tier)
            return self._finish(call, tool, task_id, f"{call.name} is not allowed yet (tier {tool.tier})", ok=False)
        if not validate(call.arguments, tool.spec.parameters):
            return self._finish(call, tool, task_id, "invalid arguments for " + call.name, ok=False)
        try:
            result = tool.handler(call.arguments)
        except Exception as e:  # a failing tool must not crash the loop
            return self._finish(call, tool, task_id, f"tool error: {e}", ok=False)
        return self._finish(call, tool, task_id, result[:MAX_RESULT_CHARS], ok=True)

    def _finish(self, call: ToolCall, tool: Tool | None, task_id: str | None, content: str, ok: bool) -> ToolResult:
        tier = tool.tier if tool else "?"
        self.store.conn.execute(
            "INSERT INTO tool_runs (task_id, tool, tier, arguments, result, ok) VALUES (?, ?, ?, ?, ?, ?)",
            (task_id, call.name, tier, json.dumps(call.arguments, ensure_ascii=False), content[:2000], int(ok)),
        )
        self.store.conn.commit()
        self.audit.write("tool_run", tool=call.name, tier=tier, ok=ok)
        return ToolResult(call.id, content, is_error=not ok)
