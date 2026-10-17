"""Astra discipline: the three gate rules of PLAN.md 27.4a, and the Brahmastra rules.

Shastra (T0, T1) is a hand weapon. Astra (T2, T3) is charged and released by Sachin's approval
and must declare its withdrawal, its samhara: a verify path or an undo tool. A T2/T3 tool with no
samhara is the Brahmastra, irreversible, and gets the strictest rules.

(a) One irreversible action in flight at a time, across all lokas. `acquire` takes the single
    slot (an atomic INSERT into `astra_inflight` only when no live row exists); `release` frees it
    after verify, success or failure. A slot older than `stale_minutes` is taken over with an
    audit line (a crashed run must not block the world for ever). A second T3 while one is in
    flight is refused with the holder named; the caller may retry later.
(b) A failed verification withdraws the grant. When a T2/T3 tool's verify fails, every active
    standing grant for that tool (in that loka, or loka-less) is revoked, `grant_withdrawn` is
    audited and the tool is marked "needs regrant" here, so the dashboard can show it; a fresh
    grant (`jarvis approvals grant`) clears the mark.
(c) Every T2/T3 tool declares its samhara (`Tool.samhara`): "verify" when it has a verifier,
    "undo:<tool>" naming the inverse tool, or "none". `declare_samhara` fills the known tools;
    `enforce_samhara` raises a T2 tool without one to T3 irreversible (audited once).
Brahmastra (T3 irreversible): one exact target (`single_target` refuses lists longer than one,
globs and "all"), released once per approval (`release_once` consumes the approval id), and one
in flight (rule a).
"""

from __future__ import annotations

import re
import sqlite3
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Callable

DEFAULT_STALE_MINUTES = 30
SAMHARA_VERIFY = "verify"
SAMHARA_NONE = "none"
UNDO_PREFIX = "undo:"
# Arguments that name WHERE an action goes or WHAT it touches: the Brahmastra's one target.
TARGET_ARGS = ("path", "source", "destination", "url", "to", "cc", "bcc", "recipient", "recipients",
               "target", "file", "files", "paths", "id", "ids", "event_id", "message_id", "name")
_GLOB_CHARS = ("*", "?", "[")
_ALL_WORDS = frozenset({"all", "*", "everything", "everyone", "every"})
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

# Known tools and their withdrawal. A T2/T3 tool missing here, or set to "none", is irreversible.
KNOWN_SAMHARA: dict[str, str] = {
    "write_file": SAMHARA_VERIFY,
    "overwrite_file": SAMHARA_VERIFY,        # the old version is kept; verify re-reads the file
    "move_file": UNDO_PREFIX + "move_file",  # moving back is the inverse
    "delete_file": UNDO_PREFIX + "restore",  # the workspace trash keeps it (restore = move out of trash)
    "create_docx": SAMHARA_VERIFY,
    "create_xlsx": SAMHARA_VERIFY,
    "calendar_create_event": SAMHARA_VERIFY,
    "gmail_draft": SAMHARA_VERIFY,
    "gmail_send": SAMHARA_NONE,              # a sent mail cannot be withdrawn
    "reminder_create": SAMHARA_VERIFY,
    "notes_create": SAMHARA_VERIFY,
    "open_app": SAMHARA_VERIFY,
    "open_url": SAMHARA_NONE,                # the page is opened; nothing brings that back
    "set_brightness": UNDO_PREFIX + "set_brightness",
    "browser_fill": SAMHARA_VERIFY,
    "browser_submit": SAMHARA_NONE,          # a submitted form is out of the hand
    "code_write": SAMHARA_VERIFY,
    "bill_add": SAMHARA_VERIFY,
    "wallet_add": SAMHARA_VERIFY,
    "bill_upi_link": SAMHARA_NONE,
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS astra_inflight (
    id INTEGER PRIMARY KEY,
    tool TEXT NOT NULL,
    workspace TEXT NOT NULL DEFAULT '',
    ref TEXT,                       -- task or session id
    since REAL NOT NULL,
    released REAL,
    state TEXT NOT NULL,            -- live | released | taken_over | needs_regrant | regranted
    note TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS astra_inflight_state ON astra_inflight(state);
CREATE TABLE IF NOT EXISTS astra_releases (
    approval_id INTEGER PRIMARY KEY,
    tool TEXT NOT NULL,
    ts REAL NOT NULL
);
"""


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class Inflight:
    id: int
    tool: str
    workspace: str
    ref: str | None
    since: float

    def describe(self) -> str:
        where = f" in {self.workspace}" if self.workspace else ""
        return f"tool {self.tool}{where} since {_iso(self.since)}"


class AstraStore:
    def __init__(self, conn: sqlite3.Connection, audit: Any = None, clock: Callable[[], float] = time.time,
                 stale_minutes: float = DEFAULT_STALE_MINUTES):
        self.conn = conn
        self.audit = audit
        self.clock = clock
        self.stale_s = float(stale_minutes) * 60
        conn.executescript(_SCHEMA)

    def _audit(self, event: str, **fields: Any) -> None:
        if self.audit is not None:
            self.audit.write(event, **fields)

    # ---- rule (a): one in flight ----

    def live(self) -> Inflight | None:
        r = self.conn.execute("SELECT id, tool, workspace, ref, since FROM astra_inflight WHERE state='live' "
                              "ORDER BY since LIMIT 1").fetchone()
        return Inflight(*r) if r else None

    def acquire(self, tool: str, workspace: str = "", ref: str | None = None) -> tuple[int | None, str | None]:
        """Take the single slot. Returns (row id, None) or (None, why not). A stale holder is
        taken over (audited) so one crashed run never blocks every loka for good."""
        now = self.clock()
        holder = self.live()
        if holder is not None and now - holder.since >= self.stale_s:
            self.conn.execute("UPDATE astra_inflight SET state='taken_over', released=?, note=? WHERE id=? AND state='live'",
                              (now, f"stale after {int(self.stale_s // 60)} min; taken over by {tool}", holder.id))
            self.conn.commit()
            self._audit("astra_stale_takeover", held_by=holder.tool, workspace=holder.workspace, ref=holder.ref,
                        since=_iso(holder.since), taken_by=tool)
        # Atomic: the INSERT happens only when no live row exists at that moment.
        cur = self.conn.execute(
            "INSERT INTO astra_inflight (tool, workspace, ref, since, state) "
            "SELECT ?, ?, ?, ?, 'live' WHERE NOT EXISTS (SELECT 1 FROM astra_inflight WHERE state='live')",
            (tool, workspace or "", ref, now))
        self.conn.commit()
        if cur.rowcount == 1:
            return cur.lastrowid, None
        holder = self.live()
        why = f"another irreversible action is in flight ({holder.describe()})" if holder else \
            "another irreversible action is in flight"
        self._audit("astra_refused_inflight", tool=tool, workspace=workspace, ref=ref,
                    holder=holder.tool if holder else None)
        return None, why

    def release(self, slot: int, ok: bool | None = None) -> None:
        note = "" if ok is None else ("verified" if ok else "verification failed")
        self.conn.execute("UPDATE astra_inflight SET state='released', released=?, note=? WHERE id=? AND state='live'",
                          (self.clock(), note, slot))
        self.conn.commit()

    # ---- rule (b): a failed verification withdraws the grant ----

    def mark_needs_regrant(self, tool: str, workspace: str = "", ref: str | None = None, note: str = "") -> None:
        self.conn.execute("INSERT INTO astra_inflight (tool, workspace, ref, since, state, note) "
                          "VALUES (?, ?, ?, ?, 'needs_regrant', ?)", (tool, workspace or "", ref, self.clock(), note[:300]))
        self.conn.commit()

    def needs_regrant(self, workspace: str | None = None) -> list[dict]:
        """Tools whose last verification failed and that wait for Sachin's fresh grant (dashboard)."""
        rows = self.conn.execute("SELECT id, tool, workspace, ref, since, note FROM astra_inflight "
                                 "WHERE state='needs_regrant' ORDER BY since DESC").fetchall()
        out = [{"id": r[0], "tool": r[1], "workspace": r[2], "ref": r[3], "since": _iso(r[4]), "note": r[5]} for r in rows]
        if workspace is not None:
            out = [x for x in out if x["workspace"] in ("", workspace)]
        return out

    def clear_regrant(self, tool: str, workspace: str = "") -> int:
        """A fresh grant was made: the mark is lifted (for the loka, or every loka when none given)."""
        if workspace:
            cur = self.conn.execute("UPDATE astra_inflight SET state='regranted', released=? WHERE state='needs_regrant' "
                                    "AND tool=? AND workspace IN ('', ?)", (self.clock(), tool, workspace))
        else:
            cur = self.conn.execute("UPDATE astra_inflight SET state='regranted', released=? WHERE state='needs_regrant' "
                                    "AND tool=?", (self.clock(), tool))
        self.conn.commit()
        return cur.rowcount

    # ---- Brahmastra: released once per approval ----

    def release_once(self, approval_id: int | None, tool: str) -> bool:
        """Consume one approval. False when it was already used (or there is none to consume)."""
        if approval_id is None:
            return False
        try:
            self.conn.execute("INSERT INTO astra_releases (approval_id, tool, ts) VALUES (?, ?, ?)",
                              (int(approval_id), tool, self.clock()))
        except sqlite3.IntegrityError:
            self.conn.commit()
            self._audit("astra_approval_reused", tool=tool, approval_id=approval_id)
            return False
        self.conn.commit()
        return True


# ---- Brahmastra: one exact target ----

def single_target(arguments: dict) -> str | None:
    """Why these arguments name more than one exact target (or none), or None when they are fit
    for an irreversible action: no list longer than one, no glob, no 'all'."""
    for key, value in arguments.items():
        if isinstance(value, list):
            if len(value) > 1:
                return f"{key} names {len(value)} targets; an irreversible action takes exactly one"
            value = value[0] if value else None
        if not isinstance(value, str):
            continue
        text = value.strip()
        is_target = key in TARGET_ARGS
        if is_target and text.lower() in _ALL_WORDS:
            return f"{key} is '{text}'; an irreversible action needs one exact target"
        if is_target and any(c in text for c in _GLOB_CHARS):
            return f"{key} contains a wildcard ({text[:60]}); an irreversible action needs one exact target"
        if key in ("to", "cc", "bcc", "recipient", "recipients"):
            emails = _EMAIL_RE.findall(text)
            if len(emails) > 1 or (len(emails) == 1 and ("," in text or ";" in text)):
                return f"{key} names more than one recipient; an irreversible action takes exactly one"
    return None


# ---- rule (c): samhara ----

def tool_samhara(tool: Any) -> str:
    """The effective withdrawal of a tool: its declared samhara, else "verify" when it has a
    verifier, else "none"."""
    declared = (getattr(tool, "samhara", "") or "").strip()
    if declared == SAMHARA_VERIFY:
        return SAMHARA_VERIFY if getattr(tool, "verify", None) else SAMHARA_NONE
    if declared.startswith(UNDO_PREFIX) and len(declared) > len(UNDO_PREFIX):
        return declared
    if declared in ("", SAMHARA_NONE):
        return SAMHARA_VERIFY if (declared == "" and getattr(tool, "verify", None)) else SAMHARA_NONE
    return SAMHARA_NONE  # an unknown word is no withdrawal


def is_irreversible(tool: Any) -> bool:
    """The Brahmastra: T3 with no withdrawal."""
    return getattr(tool, "tier", "") == "T3" and tool_samhara(tool) == SAMHARA_NONE


def declare_samhara(reg: Any, known: dict[str, str] | None = None) -> list[str]:
    """Fill `samhara` on the registry's known tools (the catalog calls this once). Returns the
    names it set. A tool that already declares one keeps it."""
    table = KNOWN_SAMHARA if known is None else known
    done: list[str] = []
    for name, value in table.items():
        tool = reg.get(name)
        if tool is None or getattr(tool, "samhara", ""):
            continue
        reg.register(replace(tool, samhara=value))
        done.append(name)
    return done


def enforce_samhara(reg: Any, audit: Any = None) -> list[str]:
    """A T2 tool with no samhara is treated as the Brahmastra: raised to T3 (audited once).
    Returns the names raised. T3 tools without one are already irreversible by tier."""
    raised: list[str] = []
    for tool in reg.all():
        if tool.tier == "T2" and tool_samhara(tool) == SAMHARA_NONE:
            reg.register(replace(tool, tier="T3", samhara=SAMHARA_NONE))
            raised.append(tool.spec.name)
            if audit is not None:
                audit.write("samhara_missing", tool=tool.spec.name, was="T2", now="T3",
                            reason="no undo or verify path declared; treated as irreversible")
    return raised
