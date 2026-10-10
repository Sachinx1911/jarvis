"""Approve or deny an action that an unattended schedule run queued (PLAN.md 10.3).

Approving replays the exact queued tool call once:
- the item must still be pending (an atomic status change, so a second click does nothing);
- it must be younger than `max_age` (default 24 h): an old request may no longer fit;
- T4 never runs, whatever was stored, and the emergency stop blocks replays;
- it runs through a fresh ToolRegistry (the same tools a scheduled chat turn gets) with an
  approver that says yes only to that tool with arguments whose SHA-256 of canonical JSON
  matches the stored ones. Any other approval request during the replay is denied;
- the result and the verifier's verdict are stored on the item, written to the audit log
  and sent back through the notifier.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable

from jarvis.control.approvals import ApprovalRequest, Approver
from jarvis.control.stop import StopSwitch
from jarvis.proactive.scheduler import PendingApprovals
from jarvis.providers.base import ToolCall

DEFAULT_MAX_AGE = timedelta(hours=24)

# (runtime, approver) -> jarvis.tools.registry.ToolRegistry
RegistryFactory = Callable[[Any, Approver], Any]


def args_sha256(arguments: dict) -> str:
    canonical = json.dumps(arguments, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def exact_approver(tool: str, arguments: dict, audit: Any = None, pending_id: int | None = None) -> Approver:
    """Approves only `tool` with exactly these arguments, and only once."""
    want = args_sha256(arguments)
    used = {"done": False}

    def approve(req: ApprovalRequest) -> bool:
        match = req.tool == tool and args_sha256(req.arguments) == want and not used["done"]
        if match:
            used["done"] = True
        elif audit is not None:
            audit.write("replay_mismatch_denied", pending_id=pending_id, wanted_tool=tool, tool=req.tool,
                        tier=req.tier, arguments_sha256=args_sha256(req.arguments), wanted_sha256=want)
        return match
    return approve


@dataclass
class ReplayOutcome:
    pending_id: int
    status: str            # executed | failed | denied | stale | refused | not_pending | unknown | stopped
    message: str
    ok: bool = False
    verified: bool | None = None


def _verified(content: str) -> bool | None:
    if "\n[verified:" in content:
        return True
    if "\n[NOT verified:" in content:
        return False
    return None


def _age(created_at: str, now: datetime) -> timedelta:
    created = datetime.fromisoformat(created_at)
    if (created.tzinfo is None) != (now.tzinfo is None):
        created = created.replace(tzinfo=now.tzinfo)
    return now - created


def _notify(notifier: Any, text: str) -> None:
    if notifier is None:
        return
    try:
        notifier.send(text, "Approval")
    except Exception:  # noqa: BLE001 - the result is stored and audited anyway
        pass


def deny_pending(rt: Any, pid: int, now: datetime, notifier: Any = None, source: str = "cli") -> ReplayOutcome:
    pending = PendingApprovals(rt.store.conn)
    item = pending.get(pid)
    if item is None:
        return ReplayOutcome(pid, "unknown", f"No pending approval #{pid}.")
    if not pending.set_status(pid, "denied", now):
        return ReplayOutcome(pid, "not_pending", f"#{pid} is already {item['status']}.")
    rt.audit.write("pending_approval_denied", pending_id=pid, tool=item["tool"], tier=item["tier"], source=source)
    return ReplayOutcome(pid, "denied", f"Denied #{pid}: {item['tool']} will not run.")


def approve_pending(rt: Any, pid: int, now: datetime, registry_factory: RegistryFactory, notifier: Any = None,
                    max_age: timedelta = DEFAULT_MAX_AGE, source: str = "cli",
                    clock: Callable[[], datetime] | None = None) -> ReplayOutcome:
    pending = PendingApprovals(rt.store.conn)
    item = pending.get(pid)
    if item is None:
        return ReplayOutcome(pid, "unknown", f"No pending approval #{pid}.")
    if item["status"] != "pending":
        return ReplayOutcome(pid, "not_pending", f"#{pid} is already {item['status']}.")
    tool, tier, arguments = item["tool"], item["tier"], item["arguments"]
    audit = rt.audit

    if tier == "T4":
        pending.set_status(pid, "refused", now)
        audit.write("pending_approval_refused", pending_id=pid, tool=tool, reason="T4 never runs", source=source)
        return ReplayOutcome(pid, "refused", f"#{pid} ({tool}) is prohibited (T4) and never runs.")
    try:
        age = _age(item["created_at"], now)
    except ValueError:
        age = max_age + timedelta(seconds=1)
    if age > max_age:
        pending.set_status(pid, "stale", now)
        audit.write("pending_approval_stale", pending_id=pid, tool=tool, age_hours=round(age.total_seconds() / 3600, 1),
                    source=source)
        hours = int(max_age.total_seconds() // 3600)
        return ReplayOutcome(pid, "stale", f"#{pid} is older than {hours} h and can no longer be approved. "
                                           f"Ask me again if it is still needed.")
    if StopSwitch(rt.paths.data).engaged():
        return ReplayOutcome(pid, "stopped", "Emergency stop is ON; nothing runs. /resume first.")
    if not pending.set_status(pid, "running", now):
        return ReplayOutcome(pid, "not_pending", f"#{pid} was already handled.")

    audit.write("pending_approval_approved", pending_id=pid, tool=tool, tier=tier, source=source,
                arguments_sha256=args_sha256(arguments))
    approver = exact_approver(tool, arguments, audit, pid)
    try:
        registry = registry_factory(rt, approver)
        result = registry.execute(ToolCall(f"replay-{pid}", tool, arguments), task_id=None, agent="approval-replay")
        content, ok = result.content, not result.is_error
    except Exception as e:  # noqa: BLE001 - record the failure on the item
        content, ok = f"replay error: {type(e).__name__}: {e}", False
    verified = _verified(content) if ok else None
    done = clock() if clock else now
    status = "executed" if ok else "failed"
    pending.finish(pid, status, content, ok, verified, done)
    audit.write("pending_approval_replayed", pending_id=pid, tool=tool, tier=tier, status=status, ok=ok,
                verified=verified, source=source,
                output_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest())
    head = f"Approved #{pid}: {tool} " + ("ran" if ok else "did NOT run")
    if verified is not None:
        head += ", verified" if verified else ", NOT verified"
    message = f"{head}.\n{content[:1500]}"
    _notify(notifier, message)
    return ReplayOutcome(pid, status, message, ok, verified)
