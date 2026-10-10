"""Risk-tier gate (PLAN.md 11.1) with approvals.

T0 read-only: runs.            T1 local write: runs, then verified (asks once the session is tainted).
T2 significant change: asks.   T3 external / irreversible: always asks, full details.
T4 prohibited: never runs; the attempt is logged.

The approver sees the exact arguments. With no approver (e.g. a one-shot command),
anything that needs approval is denied.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable

from jarvis.control.audit import AuditLog
from jarvis.db import Store


@dataclass(frozen=True)
class ApprovalRequest:
    tool: str
    tier: str
    arguments: dict
    reason: str  # why approval is needed

    def describe(self) -> str:
        args = json.dumps(self.arguments, ensure_ascii=False, indent=2)
        return f"Jarvis wants to run {self.tool} (tier {self.tier}, {self.reason}) with:\n{args}"


Approver = Callable[[ApprovalRequest], bool]


class ApprovalGate:
    def __init__(self, store: Store, audit: AuditLog, approver: Approver | None = None):
        self.store = store
        self.audit = audit
        self.approver = approver

    @staticmethod
    def needs_approval(tier: str, tainted: bool) -> str | None:
        """Reason approval is needed, or None if the tool may run directly."""
        if tier == "T0":
            return None
        if tier == "T1":
            return "session has read untrusted web content" if tainted else None
        if tier == "T2":
            return "significant change"
        return "external or irreversible action"

    def check(self, tool: str, tier: str, arguments: dict, tainted: bool, task_id: str | None) -> tuple[bool, str]:
        if tier == "T4":
            self._record(task_id, tool, arguments, "blocked_t4")
            self.audit.write("t4_attempt", tool=tool, arguments=arguments)
            return False, "prohibited (T4); never runs"
        reason = self.needs_approval(tier, tainted)
        if reason is None:
            return True, "auto"
        if self.approver is None:
            self._record(task_id, tool, arguments, "denied_no_approver")
            return False, "needs approval, but nobody can approve here"
        approved = bool(self.approver(ApprovalRequest(tool, tier, arguments, reason)))
        self._record(task_id, tool, arguments, "approved" if approved else "denied")
        return approved, "approved by user" if approved else "denied by user"

    def _record(self, task_id: str | None, tool: str, arguments: dict, decision: str) -> None:
        action = json.dumps({"tool": tool, "arguments": arguments}, ensure_ascii=False)
        self.store.conn.execute("INSERT INTO approvals (task_id, action, decision) VALUES (?, ?, ?)",
                                (task_id, action, decision))
        self.store.conn.commit()
        self.audit.write("approval", tool=tool, decision=decision)
