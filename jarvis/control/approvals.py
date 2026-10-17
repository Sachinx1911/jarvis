"""Risk-tier gate (PLAN.md 11.1) with approvals.

T0 read-only: runs.            T1 local write: runs, then verified (asks once the session is tainted).
T2 significant change: asks.   T3 external / irreversible: always asks, full details.
T4 prohibited: never runs; the attempt is logged.

The approver sees the exact arguments, plus highlighted risky parts (links, email addresses,
long encoded strings) and where each value came from when Jarvis can tell: the user's own
words, untrusted outside text (web, mail, calendar), or written by the model. A long argument
is easy to approve without reading; the highlights are what a tired user should check.
With no approver (e.g. a one-shot command), anything that needs approval is denied.

Effect previews (jarvis/control/preview.py): every request carries what will change (diff,
path and size, the exact event or email, the URL with its domain marked), shown first.

Fewer, better questions (research 2026-10-10, approval fatigue):
- Standing grants (jarvis/control/grants.py): Sachin pre-approves one exact pattern. Used only
  for T1/T2, never in a hostile session, never when egress rules flag the call; every use is
  counted and audited. Unattended runs (no approver) may use them.
- Grouped low-risk steps: when a second new-file write in a row in the same folder needs
  approval, the question offers "allow new files in this folder for the rest of this session";
  that session grant lives only in this gate (one chat or task) and never survives it.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from jarvis.control.audit import AuditLog
from jarvis.control.egress import EMAIL_RE, ENCODED_RE, suspicious_url, urls_in, looks_encoded
from jarvis.control.grants import GRANTABLE_TIERS, GrantStore, SessionGrant
from jarvis.control.preview import preview, roots_for, target_folder
from jarvis.db import Store

MAX_NOTES = 8
MAX_REASON_NOTES_CHARS = 300
SESSION_GRANT_MAX_S = 4 * 3600   # a grouped approval ends with the session, or after 4 hours
GROUPABLE_TOOLS = frozenset({"write_file"})  # T1 new-file writes (never overwrite, move or delete)


@dataclass(frozen=True)
class ApprovalRequest:
    tool: str
    tier: str
    arguments: dict
    reason: str  # why approval is needed (carries a short CHECK summary when there are notes)
    notes: tuple[str, ...] = ()  # highlighted risky parts, one per line
    preview: str = ""  # what will change (jarvis/control/preview.py); [[...]] marks what to check
    scope: str = ""    # non-empty: approving also grants this for the rest of the session

    def describe(self) -> str:
        """Effect first (Telegram shows only the first lines), then the exact arguments."""
        args = json.dumps(self.arguments, ensure_ascii=False, indent=2)
        out = f"Jarvis wants to run {self.tool} (tier {self.tier}, {self.reason})"
        if self.preview:
            out += f"\nWHAT WILL HAPPEN:\n{self.preview}"
        if self.scope:
            out += f"\nALSO: {self.scope}"
        out += f"\nwith:\n{args}"
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
    def __init__(self, store: Store, audit: AuditLog, approver: Approver | None = None,
                 roots: list[Path] | None = None, clock: Callable[[], float] = time.time):
        self.store = store
        self.audit = audit
        self.approver = approver
        self.clock = clock
        self._roots = roots
        self._roots_known = roots is not None
        self._grants: GrantStore | None = None
        self._session_grants: list[SessionGrant] = []
        self._last_t1: tuple[Path, str | None] | None = None  # folder of the last approved new-file write
        self.workspace: str = ""          # the loka asking; a loka-bound grant answers only there
        self.last_approval_id: int | None = None  # row of the last recorded decision (astra: released once)

    @property
    def roots(self) -> list[Path] | None:
        """Allowed file folders (previews, path rules, folder grants); read from the home that
        owns this database unless given."""
        if not self._roots_known:
            self._roots = roots_for(self.store.conn)
            self._roots_known = True
        return self._roots

    @property
    def grants(self) -> GrantStore:
        if self._grants is None:
            self._grants = GrantStore(self.store.conn, self.roots, self.clock)
        return self._grants

    @staticmethod
    def standing_allowed(tier: str, tainted: bool, hostile: bool | None, force_reason: str | None,
                         notes: tuple[str, ...]) -> bool:
        """May a standing grant answer for Sachin here? Never for T3/T4, never when egress rules
        flag the call, never in a hostile session. hostile=None means the caller did not say:
        a tainted session then counts as hostile (fail closed)."""
        if tier not in GRANTABLE_TIERS or force_reason:
            return False
        if hostile or (hostile is None and tainted):
            return False
        return not any("WARNING" in n for n in notes)

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
              force_reason: str | None = None, notes: tuple[str, ...] = (),
              hostile: bool | None = None) -> tuple[bool, str]:
        """force_reason: ask even when the tier alone would not (egress rule for tainted sessions).
        hostile: the session saw a prompt-injection attempt (None = not told; grants fail closed)."""
        if tier == "T4":
            self._record(task_id, tool, arguments, "blocked_t4")
            self.audit.write("t4_attempt", tool=tool, arguments=arguments)
            return False, "prohibited (T4); never runs"
        reason = self.needs_approval(tier, tainted)
        if force_reason:
            reason = f"{reason}; {force_reason}" if reason else force_reason
        if reason is None:
            return True, "auto"

        flagged = bool(force_reason) or any("WARNING" in n for n in notes)
        if self.standing_allowed(tier, tainted, hostile, force_reason, notes):
            used = self._use_standing(tool, tier, arguments, task_id)
            if used:
                return True, used
        folder = self._folder(tool, tier, arguments)
        if folder is not None and hostile is not True and not flagged:
            if self._session_grant(folder, task_id) is not None:
                self._record(task_id, tool, arguments, "approved_session_grant")
                self.audit.write("session_grant_used", tool=tool, folder=str(folder), task_id=task_id)
                return True, "approved for this folder earlier in this session"

        if self.approver is None:
            self._record(task_id, tool, arguments, "denied_no_approver")
            return False, "needs approval, but nobody can approve here"
        if notes:
            summary = "; ".join(notes)
            if len(summary) > MAX_REASON_NOTES_CHARS:
                summary = summary[:MAX_REASON_NOTES_CHARS] + "..."
            reason = f"{reason}. CHECK: {summary}"
            self.audit.write("approval_highlights", tool=tool, notes=list(notes))
        offer = (folder is not None and self._last_t1 == (folder, task_id) and hostile is not True
                 and not flagged)
        scope = (f"Approving also allows creating new files in {self._show(folder)} for the rest of this "
                 "session (new files only; ends when this chat or task ends)") if offer and folder else ""
        req = ApprovalRequest(tool, tier, arguments, reason, tuple(notes),
                              preview=preview(tool, arguments, self.roots), scope=scope)
        approved = bool(self.approver(req))
        self._record(task_id, tool, arguments, "approved" if approved else "denied")
        if approved and folder is not None:
            if offer:
                self._session_grants.append(SessionGrant(folder, task_id, self.clock() + SESSION_GRANT_MAX_S))
                self.audit.write("session_grant_created", tool=tool, folder=str(folder), task_id=task_id)
            self._last_t1 = (folder, task_id)
        else:
            self._last_t1 = None
        return approved, "approved by user" if approved else "denied by user"

    # ---- standing and session grants ----

    def _use_standing(self, tool: str, tier: str, arguments: dict, task_id: str | None) -> str | None:
        try:
            grant = self.grants.find(tool, tier, arguments, self.workspace)
            if grant is None or not self.grants.consume(grant, task_id, arguments):
                return None
        except Exception as e:  # a broken grant table must never approve anything
            self.audit.write("grant_error", tool=tool, error=f"{type(e).__name__}: {e}")
            return None
        self._record(task_id, tool, arguments, f"approved_grant:{grant.id}")
        self.audit.write("grant_used", grant_id=grant.id, tool=tool, tier=tier, task_id=task_id,
                         arguments=arguments, use=grant.uses + 1, max_uses=grant.max_uses)
        return f"approved by standing grant {grant.id}"

    def _folder(self, tool: str, tier: str, arguments: dict) -> Path | None:
        if tier != "T1" or tool not in GROUPABLE_TOOLS:
            return None
        try:
            return target_folder(tool, arguments, self.roots)
        except Exception:
            return None

    def _session_grant(self, folder: Path, task_id: str | None) -> SessionGrant | None:
        now = self.clock()
        self._session_grants = [g for g in self._session_grants if g.expires > now]
        return next((g for g in self._session_grants if g.folder == folder and g.task_id == task_id), None)

    def end_session(self) -> None:
        """Drop the grouped approvals now (they also die with this gate, i.e. the chat or task)."""
        if self._session_grants:
            self.audit.write("session_grants_ended", count=len(self._session_grants))
        self._session_grants = []
        self._last_t1 = None

    def _show(self, folder: Path) -> str:
        for r in self.roots or []:
            root = r.expanduser().resolve()
            if folder == root:
                return root.name
            if folder.is_relative_to(root):
                return f"{root.name}/{folder.relative_to(root).as_posix()}"
        return str(folder)

    def _record(self, task_id: str | None, tool: str, arguments: dict, decision: str) -> None:
        action = json.dumps({"tool": tool, "arguments": arguments}, ensure_ascii=False)
        cur = self.store.conn.execute("INSERT INTO approvals (task_id, action, decision) VALUES (?, ?, ?)",
                                      (task_id, action, decision))
        self.store.conn.commit()
        self.last_approval_id = cur.lastrowid
        self.audit.write("approval", tool=tool, decision=decision)
