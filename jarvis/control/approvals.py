"""Risk-tier gate (PLAN.md 11.1) with approvals.

T0 read-only: runs.            T1 local write: runs, then verified (asks once the session is tainted).
T2 significant change: asks.   T3 external / irreversible: always asks, full details.
T4 prohibited: never runs; the attempt is logged.

The approver sees the exact arguments, plus highlighted risky parts (links, email addresses,
long encoded strings) and where each value came from when Jarvis can tell: the user's own
words, untrusted outside text (web, mail, calendar), or written by the model. A long argument
is easy to approve without reading; the highlights are what a tired user should check.
With no approver (e.g. a one-shot command), anything that needs approval is denied.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable

from jarvis.control.audit import AuditLog
from jarvis.control.egress import EMAIL_RE, ENCODED_RE, suspicious_url, urls_in, looks_encoded
from jarvis.db import Store

MAX_NOTES = 8
MAX_REASON_NOTES_CHARS = 300


@dataclass(frozen=True)
class ApprovalRequest:
    tool: str
    tier: str
    arguments: dict
    reason: str  # why approval is needed (carries a short CHECK summary when there are notes)
    notes: tuple[str, ...] = ()  # highlighted risky parts, one per line

    def describe(self) -> str:
        args = json.dumps(self.arguments, ensure_ascii=False, indent=2)
        out = f"Jarvis wants to run {self.tool} (tier {self.tier}, {self.reason}) with:\n{args}"
        if self.notes:
            out += "\nCHECK THESE PARTS:\n" + "\n".join(f"  ! {n}" for n in self.notes)
        return out


Approver = Callable[[ApprovalRequest], bool]


def _origin(value: str, trusted: list[str], untrusted: list[str]) -> str:
    if any(value in t for t in trusted):
        return "from your own words"
    if any(value in u for u in untrusted):
        return "copied from untrusted outside text (web, mail or calendar)"
    return "written by the model"


def _strings(args: dict, prefix: str = "") -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for k, v in args.items():
        name = f"{prefix}{k}"
        if isinstance(v, str):
            out.append((name, v))
        elif isinstance(v, dict):
            out += _strings(v, name + ".")
        elif isinstance(v, list):
            out += [(f"{name}[{i}]", x) for i, x in enumerate(v) if isinstance(x, str)]
    return out


def risk_notes(arguments: dict, trusted: list[str], untrusted: list[str]) -> tuple[str, ...]:
    """Risky parts of tool arguments, labelled with where they came from when known."""
    notes: list[str] = []
    for name, value in _strings(arguments):
        for url in urls_in(value):
            bad = suspicious_url(url)
            notes.append(f"{name}: link {url[:160]} ({_origin(url, trusted, untrusted)})"
                         + (f"; WARNING: {bad}" if bad else ""))
        for email in dict.fromkeys(EMAIL_RE.findall(value)):
            if any(email in u for u in urls_in(value)):
                continue
            notes.append(f"{name}: email address {email} ({_origin(email, trusted, untrusted)})")
        if looks_encoded(value):
            run = max((m.group(0) for m in ENCODED_RE.finditer(value)), key=len)
            notes.append(f"{name}: long encoded string {run[:40]}... ({len(run)} characters); "
                         "it can hide data being sent out")
        if len(value) > 200 and untrusted and any(value[:80] in u for u in untrusted):
            notes.append(f"{name}: this text was copied from untrusted outside text")
    return tuple(dict.fromkeys(notes))[:MAX_NOTES]


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
            return "session has read untrusted outside content" if tainted else None
        if tier == "T2":
            return "significant change"
        return "external or irreversible action"

    def check(self, tool: str, tier: str, arguments: dict, tainted: bool, task_id: str | None,
              force_reason: str | None = None, notes: tuple[str, ...] = ()) -> tuple[bool, str]:
        """force_reason: ask even when the tier alone would not (egress rule for tainted sessions)."""
        if tier == "T4":
            self._record(task_id, tool, arguments, "blocked_t4")
            self.audit.write("t4_attempt", tool=tool, arguments=arguments)
            return False, "prohibited (T4); never runs"
        reason = self.needs_approval(tier, tainted)
        if force_reason:
            reason = f"{reason}; {force_reason}" if reason else force_reason
        if reason is None:
            return True, "auto"
        if self.approver is None:
            self._record(task_id, tool, arguments, "denied_no_approver")
            return False, "needs approval, but nobody can approve here"
        if notes:
            summary = "; ".join(notes)
            if len(summary) > MAX_REASON_NOTES_CHARS:
                summary = summary[:MAX_REASON_NOTES_CHARS] + "..."
            reason = f"{reason}. CHECK: {summary}"
            self.audit.write("approval_highlights", tool=tool, notes=list(notes))
        approved = bool(self.approver(ApprovalRequest(tool, tier, arguments, reason, tuple(notes))))
        self._record(task_id, tool, arguments, "approved" if approved else "denied")
        return approved, "approved by user" if approved else "denied by user"

    def _record(self, task_id: str | None, tool: str, arguments: dict, decision: str) -> None:
        action = json.dumps({"tool": tool, "arguments": arguments}, ensure_ascii=False)
        self.store.conn.execute("INSERT INTO approvals (task_id, action, decision) VALUES (?, ?, ?)",
                                (task_id, action, decision))
        self.store.conn.commit()
        self.audit.write("approval", tool=tool, decision=decision)
