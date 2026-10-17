"""Typed tool registry: one registry for every provider; specs use the portable schema subset.

Order for every call: known and enabled tool -> workspace fence (jarvis/control/fence.py) ->
argument schema -> path pre-check (secret locations are T4) -> egress check (tainted sessions)
-> Brahmastra single target -> risk-tier gate and approval (always_ask forces it) -> one T3 in
flight, approval consumed once (jarvis/control/astra.py) -> run -> taint -> file provenance ->
verify (a failed T2/T3 verify withdraws the tool's grants) -> release -> log. The risk tier
never goes to a model.

Taint (prompt-injection defense): reading untrusted outside content taints the session; once
tainted, T1 tools ask too, and links the user did not give need approval. Taint is fail-closed:
every tool taints unless it is listed in CLEAN_OUTPUT below (with the reason) or declares
taints=False itself. A tool may decide per call with taint_check (e.g. read_file taints only
for files with untrusted provenance).
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from jarvis.control.approvals import ApprovalGate, risk_notes
from jarvis.control.astra import DEFAULT_STALE_MINUTES, AstraStore, is_irreversible, single_target
from jarvis.control.audit import AuditLog
from jarvis.control.egress import EgressPolicy, Verdict
from jarvis.control.fence import Fence
from jarvis.control.provenance import Provenance
from jarvis.db import Store
from jarvis.providers.base import ToolCall, ToolResult, ToolSpec
from jarvis.schema import validate
from jarvis.tools.files import PathBlocked, PathDenied

TIERS = ("T0", "T1", "T2", "T3", "T4")
MAX_RESULT_CHARS = 8000
MAX_STORED_CHARS = 4000  # tool_runs.result
MAX_VERIFY_NOTE_CHARS = 300
INJECTION_MARKER = "[injection attempt detected]"  # quarantine output; makes the session hostile
MAX_UNTRUSTED_KEPT = 40  # recent untrusted outputs kept to label approval arguments

# Tools whose output never contains outside text. Everything else taints (fail closed).
CLEAN_OUTPUT: dict[str, str] = {
    "memory_search": "memories are extracted only from the user's own messages (and 'remember' commands); "
                     "they carry the same trust as what the user types now",
    "load_skill": "a learned skill is saved only after the user reviewed and approved its draft",
    "doc_search": "project documents are files the user explicitly added and approved for a project",
    "parse_time": "pure local computation",
    "weather": "numbers and place names from the fixed Open-Meteo API, no free text from third parties",
    "write_file": "returns Jarvis's own confirmation text",
    "overwrite_file": "returns Jarvis's own confirmation text",
    "move_file": "returns Jarvis's own confirmation text",
    "delete_file": "returns Jarvis's own confirmation text",
    "open_app": "returns Jarvis's own confirmation text",
    "notify": "returns Jarvis's own confirmation text",
    "media": "returns Jarvis's own confirmation text",
    "open_url": "returns Jarvis's own confirmation text",
    "set_brightness": "returns Jarvis's own confirmation text",
    "calendar_create_event": "returns Jarvis's own confirmation text",
    "gmail_draft": "returns Jarvis's own confirmation text",
    "gmail_send": "returns Jarvis's own confirmation text",
    "reminder_create": "returns Jarvis's own confirmation text",
    "browser_fill": "returns Jarvis's own confirmation text",
    "browser_screenshot": "returns Jarvis's own confirmation text (the image is not sent to the model)",
    "code_read": "the Coder's project folder holds only code written by the Coder or the user; the Coder has "
                 "no web tools",
    "code_write": "returns Jarvis's own confirmation text",
    "run_tests": "output of the project's own tests (code written by the Coder or the user)",
}
# Tainting on purpose (documented here, enforced by the fail-closed default):
#   web_search, web_fetch, browser_open/read/click/submit/download: web pages and search results.
#   gmail_search, gmail_read: anyone can send mail.  calendar_list: anyone can send an invite.
#   reminders_list: shared Reminders lists hold other people's text.
#   session_search: past chats include replies that quoted web or mail text.
#   read_file / list_folder: only files with untrusted provenance (taint_check, see catalog.py).
#   Any new or unknown tool.


@dataclass(frozen=True)
class Tool:
    spec: ToolSpec
    tier: str
    handler: Callable[[dict], str]
    verify: Callable[[dict], tuple[bool, str]] | None = None
    precheck: Callable[[dict], None] | None = None  # raises PathBlocked / PathDenied
    taints: bool | None = None  # None: tainting unless listed in CLEAN_OUTPUT (fail closed)
    enabled: bool = True
    taint_check: Callable[[dict], str | None] | None = None  # per call: why it taints, or None
    writes: Callable[[dict], list[Path]] | None = None       # files written (provenance records)
    url_args: tuple[str, ...] = ()   # arguments holding a URL that leaves the machine (egress)
    text_args: tuple[str, ...] = ()  # free text that leaves the machine (e.g. a search query)
    # Astra rule (c), PLAN.md 27.4a: how a T2/T3 action is withdrawn. "verify" (needs `verify`),
    # "undo:<tool>" naming the inverse tool, or "none". "" = undeclared: "verify" when a verifier
    # exists, else "none". A T2/T3 tool with none is the Brahmastra: T3 irreversible.
    samhara: str = ""


def output_taints(tool: Tool) -> bool:
    if tool.taints is not None:
        return tool.taints
    return tool.spec.name not in CLEAN_OUTPUT


@dataclass
class ToolRegistry:
    store: Store
    audit: AuditLog
    gate: ApprovalGate | None = None
    tainted: bool = False
    hostile: bool = False  # the quarantine saw an injection attempt: stricter egress
    _tools: dict[str, Tool] = field(default_factory=dict)
    trusted_text: Callable[[], list[str]] = field(default=lambda: [])  # the user's own words
    # T1 tools allowed to run without asking while tainted, because their paths are confined to
    # a task folder; what they write is recorded as tainted (agents' writer/operator).
    sandboxed: frozenset[str] = frozenset()
    provenance: Provenance | None = None
    _untrusted: list[str] = field(default_factory=list)
    # The loka this registry acts for (PLAN.md 27): its fence narrows the tools (never widens),
    # its name goes on astra rows and loka-bound grants.
    fence: Fence | None = None
    workspace: str = ""
    astra: AstraStore | None = None   # astra rules a and b; made on first use from the store
    astra_stale_minutes: float = DEFAULT_STALE_MINUTES

    def __post_init__(self):
        if self.gate is None:
            self.gate = ApprovalGate(self.store, self.audit)
        self.egress = EgressPolicy(self.store.conn, lambda: self.trusted_text())

    def register(self, tool: Tool) -> None:
        if tool.tier not in TIERS:
            raise ValueError(f"unknown tier {tool.tier}")
        self._tools[tool.spec.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def all(self) -> list[Tool]:
        return list(self._tools.values())

    def specs(self) -> list[ToolSpec]:
        return [t.spec for t in self._tools.values()
                if t.enabled and t.tier != "T4" and (self.fence is None or self.fence.refusal(t.spec.name) is None)]

    def set_fence(self, fence: Fence | None, workspace: str | None = None) -> None:
        """Apply a workspace's fence (a second fence only narrows the first)."""
        self.fence = fence if self.fence is None or fence is None else self.fence.narrowed_by(fence)
        if workspace is not None:
            self.workspace = workspace
        if self.gate is not None:
            self.gate.workspace = self.workspace

    def _astra(self) -> AstraStore:
        if self.astra is None:
            self.astra = AstraStore(self.store.conn, self.audit, self.gate.clock if self.gate else time.time,
                                    self.astra_stale_minutes)
        return self.astra

    def restrict(self, names: set[str]) -> None:
        """Keep only these tools (agent allowlists)."""
        self._tools = {k: v for k, v in self._tools.items() if k in names}

    def taint(self, why: str, **fields) -> None:
        if not self.tainted:
            self.audit.write("session_tainted", reason=why, **fields)
        self.tainted = True

    def _egress(self, tool: Tool, args: dict, task_id: str | None) -> Verdict:
        for key in tool.url_args:
            if isinstance(args.get(key), str):
                v = self.egress.check_url(args[key], self.tainted, self.hostile, task_id)
                if v.action != "ok":
                    return v
        for key in tool.text_args:
            if isinstance(args.get(key), str):
                v = self.egress.check_text(args[key], self.tainted)
                if v.action != "ok":
                    return v
        return Verdict("ok")

    def execute(self, call: ToolCall, task_id: str | None = None, agent: str | None = None) -> ToolResult:
        self._agent = agent
        tool = self._tools.get(call.name)
        if tool is None or not tool.enabled:
            return self._finish(call, tool, task_id, f"unknown or disabled tool: {call.name}", "refused", False)
        fenced = self.fence.refusal(call.name) if self.fence is not None else None
        if fenced:
            self.audit.write("tool_fenced", tool=call.name, agent=agent, workspace=self.workspace, reason=fenced)
            return self._finish(call, tool, task_id, f"Not run: {fenced}.", "refused_fence", False)
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

        egress = self._egress(tool, call.arguments, task_id)
        if egress.action == "refuse":
            self.audit.write("egress_blocked", tool=call.name, agent=agent, reason=egress.reason)
            return self._finish(call, tool, task_id, f"Not run: {egress.reason}.", "refused_egress", False)

        assert self.gate is not None
        # Brahmastra (T3 with no withdrawal): one exact target, named before anyone is asked.
        brahmastra = is_irreversible(tool)
        if brahmastra:
            bulk = single_target(call.arguments)
            if bulk:
                self.audit.write("astra_refused_target", tool=call.name, agent=agent, reason=bulk)
                return self._finish(call, tool, task_id, f"Not run: {bulk}.", "refused_target", False)
        sandboxed = tool.tier == "T1" and call.name in self.sandboxed
        gate_tainted = self.tainted and not sandboxed
        notes = risk_notes(call.arguments, self.trusted_text(), self._untrusted)
        force = egress.reason if egress.action == "ask" else None
        ask = self.fence.ask_reason(call.name) if self.fence is not None else None
        if ask:  # the workspace asks whatever the tier (T0 included); never a standing grant
            force = f"{force}; {ask}" if force else ask
        self.gate.workspace = self.workspace
        allowed, decision = self.gate.check(call.name, tool.tier, call.arguments, gate_tainted, task_id,
                                            force_reason=force, notes=notes, hostile=self.hostile)
        if not allowed:
            return self._finish(call, tool, task_id, f"Not run: {decision}.", decision, False)
        if sandboxed and self.tainted and decision == "auto":
            decision = "auto_sandboxed"
            self.audit.write("sandboxed_write", tool=call.name, agent=agent, arguments=call.arguments)

        slot: int | None = None
        if tool.tier == "T3":
            # Rule (a): one irreversible action in flight at a time, across every loka.
            slot, busy = self._astra().acquire(call.name, self.workspace, task_id)
            if slot is None:
                return self._finish(call, tool, task_id, f"Not run: {busy}; try again later.", "refused_inflight", False)
            if brahmastra and not self._astra().release_once(self.gate.last_approval_id, call.name):
                # Released once per approval: this approval was already spent (or none was recorded).
                self._astra().release(slot)
                return self._finish(call, tool, task_id, "Not run: this approval was already used once; ask again.",
                                    "refused_reused_approval", False)

        try:
            result = tool.handler(call.arguments)
        except (PathBlocked, PathDenied) as e:
            self._release(slot, None)
            return self._finish(call, tool, task_id, f"Not allowed: {e}.", "refused", False)
        except Exception as e:  # a failing tool must not crash the loop
            self._release(slot, False)
            return self._finish(call, tool, task_id, f"tool error: {e}", decision, False)

        why = None
        if tool.taint_check is not None:
            try:
                why = tool.taint_check(call.arguments)
            except Exception as e:  # fail closed
                why = f"provenance check failed: {e}"
        elif output_taints(tool):
            why = "read untrusted outside content"
        if why:
            self.taint(why, tool=call.name, agent=agent)
            self._untrusted = (self._untrusted + [result])[-MAX_UNTRUSTED_KEPT:]
            if INJECTION_MARKER in result and not self.hostile:
                self.hostile = True
                self.audit.write("session_hostile", tool=call.name, agent=agent)
        self._record_writes(tool, call, agent)

        verified = None
        tag = ""
        if tool.verify:
            try:
                ok, how = tool.verify(call.arguments)
            except Exception as e:
                ok, how = False, f"verifier error: {e}"
            verified = bool(ok)
            how = " ".join(str(how).split())[:MAX_VERIFY_NOTE_CHARS]
            tag = f"\n[verified: {how}]" if ok else f"\n[NOT verified: {how}]"
            if not ok and tool.tier in ("T2", "T3"):
                self._withdraw(tool, task_id, how)
        self._release(slot, verified)
        # The post-check tag stays the last line, however long the output: verify-after-act
        # (jarvis/tasks/verify.py) reads it from tool_runs as evidence.
        return self._finish(call, tool, task_id, result[:MAX_RESULT_CHARS - len(tag)] + tag, decision, True,
                            verified, tag)

    def _release(self, slot: int | None, ok: bool | None) -> None:
        if slot is not None:
            self._astra().release(slot, ok)

    def _withdraw(self, tool: Tool, task_id: str | None, how: str) -> None:
        """Astra rule (b): a deed that cannot be verified withdraws the grant for that tool in
        this loka until Sachin regrants it."""
        name = tool.spec.name
        try:
            gone = self.gate.grants.withdraw(name, self.workspace) if self.gate else []
        except Exception as e:  # a broken grant table must not hide the failed verification
            self.audit.write("grant_error", tool=name, error=f"{type(e).__name__}: {e}")
            gone = []
        self._astra().mark_needs_regrant(name, self.workspace, task_id, how)
        self.audit.write("grant_withdrawn", tool=name, workspace=self.workspace, task_id=task_id,
                         grants=[g.id for g in gone], reason=f"verification failed: {how}")

    def _record_writes(self, tool: Tool, call: ToolCall, agent: str | None) -> None:
        if tool.writes is None or self.provenance is None:
            return
        try:
            paths = tool.writes(call.arguments)
        except Exception:
            return
        for p in paths:
            self.provenance.record(p, self.tainted, f"{agent or 'jarvis'}:{call.name}")
        if self.tainted and paths:
            self.audit.write("file_provenance", tool=call.name, agent=agent, tainted=True,
                             paths=[str(p) for p in paths])

    def _finish(self, call: ToolCall, tool: Tool | None, task_id: str | None, content: str, decision: str,
                ok: bool, verified: bool | None = None, tag: str = "") -> ToolResult:
        tier = tool.tier if tool else "?"
        stored = content if len(content) <= MAX_STORED_CHARS else (
            content[:MAX_STORED_CHARS - len(tag)] + tag if tag and content.endswith(tag) else content[:MAX_STORED_CHARS])
        self.store.conn.execute(
            "INSERT INTO tool_runs (task_id, tool, tier, arguments, result, ok, agent) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (task_id, call.name, tier, json.dumps(call.arguments, ensure_ascii=False), stored, int(ok),
             getattr(self, "_agent", None)),
        )
        self.store.conn.commit()
        self.audit.write(
            "tool_run", tool=call.name, agent=getattr(self, "_agent", None), tier=tier, arguments=call.arguments, decision=decision, ok=ok,
            verified=verified, output_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            tainted=self.tainted,
        )
        return ToolResult(call.id, content, is_error=not ok)
