"""Pending-approval queue for chats and tasks started from the dashboard.

A chat or task thread calls the approver; the request waits here until Sachin clicks
Approve or Deny in the browser. No answer within the timeout, or an emergency stop,
counts as deny. The approval gate (jarvis/control/approvals.py) still records every
decision in SQLite and the audit log; this module only carries the question and answer.

To approve, the browser must send back the SHA-256 of the exact arguments it showed, so a
click always refers to the arguments on screen.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import threading
import time
from collections import deque
from dataclasses import dataclass, field

from jarvis.control.approvals import ApprovalRequest, Approver
from jarvis.control.audit import AuditLog


def args_hash(arguments: dict) -> str:
    canonical = json.dumps(arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass
class Pending:
    id: int
    source: str          # "chat:<session>" or "task:<id>"
    task_id: str | None
    tool: str
    tier: str
    arguments: dict
    reason: str
    created: float
    expires: float
    args_sha256: str
    event: threading.Event = field(default_factory=threading.Event, repr=False)
    approved: bool = False
    outcome: str = "pending"  # approved | denied | timeout | stopped

    def public(self) -> dict:
        return {"id": self.id, "source": self.source, "task_id": self.task_id, "tool": self.tool,
                "tier": self.tier, "arguments": self.arguments, "reason": self.reason,
                "created": self.created, "expires": self.expires, "args_sha256": self.args_sha256,
                "outcome": self.outcome,
                "describe": ApprovalRequest(self.tool, self.tier, self.arguments, self.reason).describe()}


class ApprovalError(Exception):
    pass


class ApprovalBroker:
    def __init__(self, audit: AuditLog, timeout_s: float = 300.0, clock=time.time):
        self.audit = audit
        self.timeout_s = timeout_s
        self.clock = clock
        self._lock = threading.Lock()
        self._ids = itertools.count(1)
        self._pending: dict[int, Pending] = {}
        self._history: deque[Pending] = deque(maxlen=50)

    def approver(self, source: str, task_id: str | None = None) -> Approver:
        def ask(req: ApprovalRequest) -> bool:
            return self.request(req, source, task_id)
        return ask

    def request(self, req: ApprovalRequest, source: str, task_id: str | None = None) -> bool:
        now = self.clock()
        p = Pending(next(self._ids), source, task_id, req.tool, req.tier, dict(req.arguments), req.reason,
                    now, now + self.timeout_s, args_hash(req.arguments))
        with self._lock:
            self._pending[p.id] = p
        self.audit.write("dashboard_approval_requested", id=p.id, source=source, tool=p.tool, tier=p.tier)
        answered = p.event.wait(self.timeout_s)
        with self._lock:
            self._pending.pop(p.id, None)
            if not answered and p.outcome == "pending":
                p.outcome, p.approved = "timeout", False
            self._history.appendleft(p)
        self.audit.write("dashboard_approval_answered", id=p.id, tool=p.tool, outcome=p.outcome)
        return p.approved

    def pending(self) -> list[dict]:
        with self._lock:
            return [p.public() for p in sorted(self._pending.values(), key=lambda p: p.id)]

    def history(self) -> list[dict]:
        with self._lock:
            return [p.public() for p in self._history]

    def resolve(self, approval_id: int, approve: bool, confirm_sha256: str = "") -> dict:
        with self._lock:
            p = self._pending.get(approval_id)
            if p is None:
                raise KeyError(approval_id)
            if approve and confirm_sha256 != p.args_sha256:
                raise ApprovalError("the arguments shown do not match the request; reload and check again")
            p.approved = approve
            p.outcome = "approved" if approve else "denied"
            p.event.set()
            return p.public()

    def deny_all(self, outcome: str = "stopped") -> int:
        with self._lock:
            items = list(self._pending.values())
            for p in items:
                p.approved, p.outcome = False, outcome
                p.event.set()
        return len(items)
