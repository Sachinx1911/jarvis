"""Workspace tool fences (PLAN.md 27.3, sadhana: what an office may use).

A workspace file names the tools its work may use (`tools: allow`), may not use (`tools: deny`)
and must ask before (`always_ask`, whatever the tier, T0 included). The registry applies the
fence in `execute` before the tier gate, and hides fenced-out tools from the model's tool list.

A fence only narrows: a tool the registry does not hold stays absent whatever the allow list
says, and a role's own allowlist (`ToolRegistry.restrict`) still applies on top. Nothing here
can lower a tier or skip an approval.
"""

from __future__ import annotations

from dataclasses import dataclass

from jarvis.workspaces.model import Workspace


@dataclass(frozen=True)
class Fence:
    allow: frozenset[str] = frozenset()       # empty = every registered tool
    deny: frozenset[str] = frozenset()
    always_ask: frozenset[str] = frozenset()
    workspace: str = ""

    def refusal(self, tool: str) -> str | None:
        """Why the fence refuses this tool, or None when it may pass (deny wins over allow)."""
        if tool in self.deny:
            return f"tool {tool} is denied in workspace {self.workspace or 'this one'}"
        if self.allow and tool not in self.allow:
            return f"tool {tool} is not in the allowed tools of workspace {self.workspace or 'this one'}"
        return None

    def ask_reason(self, tool: str) -> str | None:
        if tool in self.always_ask:
            return f"workspace {self.workspace or 'this one'} always asks before {tool}"
        return None

    def narrowed_by(self, other: "Fence") -> "Fence":
        """Both fences together: the stricter of each part."""
        allow = self.allow & other.allow if self.allow and other.allow else (self.allow or other.allow)
        return Fence(frozenset(allow), self.deny | other.deny, self.always_ask | other.always_ask,
                     self.workspace or other.workspace)


def fence_from_workspace(w: Workspace) -> Fence:
    return Fence(frozenset(w.tools_allow), frozenset(w.tools_deny), frozenset(w.always_ask), w.slug)


def fence_for(home, workspace: str) -> Fence:
    """The fence of the office `workspace` under `home`. A missing or broken workspace file must
    not stop the work, but it must not widen anything either: then the fence is empty (every
    registered tool, no always-ask), the same as the personal office."""
    from jarvis.workspaces.store import WorkspaceStore

    try:
        return fence_from_workspace(WorkspaceStore(home).get(workspace))
    except Exception:  # noqa: BLE001 - see the docstring
        return Fence(workspace=workspace)
