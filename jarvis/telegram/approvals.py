"""Approve/Deny from the phone.

The chat turn runs in a worker thread. When a tool needs approval, TelegramApprover sends
a message with the exact arguments and two buttons, then blocks that thread until the
button is pressed, the timeout passes (= denied) or /stop denies everything. The bot's
event loop keeps running meanwhile, so the button press and /stop are handled at once.
"""

from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass, field
from typing import Callable

from jarvis.control.approvals import ApprovalRequest
from jarvis.control.audit import AuditLog

MAX_ARGS_CHARS = 3000


@dataclass
class _Pending:
    req: ApprovalRequest
    event: threading.Event = field(default_factory=threading.Event)
    result: bool | None = None


class ApprovalBroker:
    """Thread-safe table of approvals waiting for a button press."""

    def __init__(self):
        self._lock = threading.Lock()
        self._pending: dict[str, _Pending] = {}

    def open(self, req: ApprovalRequest) -> str:
        token = secrets.token_hex(6)  # unguessable: a forged callback cannot approve anything
        with self._lock:
            self._pending[token] = _Pending(req)
        return token

    def resolve(self, token: str, approved: bool) -> ApprovalRequest | None:
        """Returns the request, or None if the token is unknown or already answered."""
        with self._lock:
            p = self._pending.get(token)
            if p is None or p.event.is_set():
                return None
            p.result = approved
            p.event.set()
            return p.req

    def wait(self, token: str, timeout: float) -> bool | None:
        """True/False when answered, None on timeout. The token is closed afterwards."""
        with self._lock:
            p = self._pending.get(token)
        if p is None:
            return None
        p.event.wait(timeout)
        with self._lock:
            self._pending.pop(token, None)
            return p.result if p.event.is_set() else None

    def deny_all(self) -> int:
        with self._lock:
            waiting = [p for p in self._pending.values() if not p.event.is_set()]
            for p in waiting:
                p.result = False
                p.event.set()
        return len(waiting)

    def waiting(self) -> int:
        with self._lock:
            return sum(1 for p in self._pending.values() if not p.event.is_set())


def approval_text(req: ApprovalRequest) -> str:
    text = req.describe()
    if len(text) > MAX_ARGS_CHARS:
        text = text[:MAX_ARGS_CHARS] + "\n... (arguments cut here; full text in the audit log)"
    return "Approval needed\n\n" + text


class TelegramApprover:
    """Approver callback for ChatSession. `send(text, token)` posts the buttons;
    `on_closed(token, outcome)` may edit that message afterwards."""

    def __init__(self, broker: ApprovalBroker, send: Callable[[str, str], None], timeout: float,
                 audit: AuditLog | None = None, on_closed: Callable[[str, str], None] | None = None):
        self.broker = broker
        self.send = send
        self.timeout = timeout
        self.audit = audit
        self.on_closed = on_closed

    def __call__(self, req: ApprovalRequest) -> bool:
        token = self.broker.open(req)
        try:
            self.send(approval_text(req), token)
        except Exception as e:  # noqa: BLE001 - cannot ask = no
            self.broker.resolve(token, False)
            self.broker.wait(token, 0)
            if self.audit:
                self.audit.write("telegram_approval", tool=req.tool, outcome="send_failed", detail=str(e))
            return False
        result = self.broker.wait(token, self.timeout)
        outcome = "timeout" if result is None else "approved" if result else "denied"
        if self.audit:
            self.audit.write("telegram_approval", tool=req.tool, tier=req.tier, outcome=outcome)
        if self.on_closed:
            try:
                self.on_closed(token, outcome)
            except Exception:  # noqa: BLE001 - editing the message is cosmetic
                pass
        return result is True
