"""Standing approvals: Sachin pre-approves one routine action pattern so it runs without asking.

A grant = one tool + a rule for EVERY argument + an expiry + a maximum number of uses.
Rules: glob (a path pattern inside an allowed folder), domain (a URL's site or its
subdomains), max_chars, equals, one_of, any. A call matches only when each of its
arguments has a rule and passes it; an argument without a rule means no match.

Hard limits (enforced here and again in the approval gate):
- Only T1 and T2 tools. Never T3 (send, pay, delete) or T4.
- Never in a hostile session (the quarantine saw a prompt injection), never for arguments the
  egress rules flag, never for a path the file policy refuses (secrets, outside the folders).
- Created only by Sachin, from the dashboard or `jarvis approvals grant`; the model has no
  tool for it. Every use is counted atomically and audited; revoked or expired grants stop.
"""

from __future__ import annotations

import fnmatch
import json
import os
import secrets
import sqlite3
import time
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from jarvis.control.egress import suspicious_url
from jarvis.tools.files import (MAX_WRITE_CHARS, PathBlocked, PathDenied, PathPolicy, is_foreign_windows_path,
                                is_secret_path)

GRANTABLE_TIERS = ("T1", "T2")
KINDS = ("glob", "domain", "max_chars", "equals", "one_of", "any")
MAX_DAYS = 90
MAX_USES = 1000
# Arguments that decide WHERE an action goes: "any" is never accepted for them.
WHERE_ARGS = ("path", "source", "destination", "url", "to")
PATH_ARGS = ("path", "source", "destination")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS standing_grants (
    id TEXT PRIMARY KEY,
    tool TEXT NOT NULL,
    tier TEXT NOT NULL,
    constraints TEXT NOT NULL,
    created REAL NOT NULL,
    expires REAL NOT NULL,
    max_uses INTEGER NOT NULL,
    uses INTEGER NOT NULL DEFAULT 0,
    revoked INTEGER NOT NULL DEFAULT 0,
    note TEXT NOT NULL DEFAULT '',
    created_by TEXT NOT NULL,
    last_used REAL
);
CREATE TABLE IF NOT EXISTS standing_grant_uses (
    id INTEGER PRIMARY KEY,
    grant_id TEXT NOT NULL,
    ts REAL NOT NULL,
    task_id TEXT,
    arguments TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS standing_grant_uses_grant ON standing_grant_uses(grant_id);
"""


class GrantError(ValueError):
    """A grant that may not be created."""


def _iso(ts: float | None) -> str | None:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds") if ts else None


@dataclass
class Grant:
    id: str
    tool: str
    tier: str
    constraints: dict
    created: float
    expires: float
    max_uses: int
    uses: int = 0
    revoked: bool = False
    note: str = ""
    created_by: str = ""
    last_used: float | None = None

    def status(self, now: float) -> str:
        if self.revoked:
            return "revoked"
        if now >= self.expires:
            return "expired"
        if self.uses >= self.max_uses:
            return "used up"
        return "active"

    def describe(self) -> str:
        rules = "; ".join(f"{k} {kind} {v}" for k, rule in self.constraints.items() for kind, v in rule.items())
        return f"{self.id}: {self.tool} when {rules}"

    def public(self, now: float) -> dict:
        status = self.status(now)
        return {"id": self.id, "tool": self.tool, "tier": self.tier, "constraints": self.constraints,
                "created": _iso(self.created), "expires": _iso(self.expires), "max_uses": self.max_uses,
                "uses": self.uses, "revoked": self.revoked, "note": self.note, "created_by": self.created_by,
                "last_used": _iso(self.last_used), "status": status, "active": status == "active"}


# ---- matching helpers ----

def _norm(p: str) -> str:
    return os.path.normcase(p.replace("\\", "/")).replace("\\", "/")


def _glob_match(pattern: str, path: str) -> bool:
    """Segment-wise glob: * and ? stay inside one folder; ** matches any number of folders."""
    pat = [s for s in _norm(pattern).split("/") if s != ""]
    parts = [s for s in _norm(path).split("/") if s != ""]

    def go(i: int, j: int) -> bool:
        if i == len(pat):
            return j == len(parts)
        if pat[i] == "**":
            return any(go(i + 1, k) for k in range(j, len(parts) + 1))
        return j < len(parts) and fnmatch.fnmatchcase(parts[j], pat[i]) and go(i + 1, j + 1)

    return go(0, 0)


def _host(url: str) -> str | None:
    try:
        p = urllib.parse.urlsplit(url.strip())
    except ValueError:
        return None
    if p.scheme not in ("http", "https") or not p.hostname:
        return None
    return p.hostname.lower().rstrip(".")


def _plain(value) -> str | None:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (str, int, float)):
        return str(value)
    return None


class GrantStore:
    def __init__(self, conn: sqlite3.Connection, roots: list[Path] | None = None, clock=time.time):
        self.conn = conn
        self.clock = clock
        self.policy = PathPolicy(roots) if roots else None
        conn.executescript(_SCHEMA)

    # ---- create, list, revoke ----

    def _abs_glob(self, pattern: str) -> str:
        if self.policy is None:
            raise GrantError("the allowed file folders are unknown here, so no path rule can be made")
        pattern = pattern.strip().replace("\\", "/")
        if not pattern or ".." in pattern.split("/"):
            raise GrantError("a path rule must not be empty or contain '..'")
        if is_foreign_windows_path(pattern):
            raise GrantError(f"path rule {pattern!r} is not inside an allowed folder (a Windows path on this computer)")
        raw = Path(pattern).expanduser()
        full = raw if raw.is_absolute() else self.policy.roots[0] / raw
        fixed = []  # the part before the first wildcard must be inside an allowed folder
        for part in full.parts:
            if any(c in part for c in "*?["):
                break
            fixed.append(part)
        base = Path(*fixed) if fixed else full
        if is_secret_path(full):
            raise GrantError("a path rule may never cover secret locations")
        try:
            self.policy.resolve(str(base))
        except (PathBlocked, PathDenied) as e:
            raise GrantError(f"path rule {pattern!r} is not inside an allowed folder ({e})")
        return full.as_posix()

    def _check_rules(self, constraints: dict) -> dict:
        if not isinstance(constraints, dict) or not constraints:
            raise GrantError("a grant needs at least one argument rule")
        out: dict = {}
        for arg, rule in constraints.items():
            if not isinstance(arg, str) or not arg or not isinstance(rule, dict) or len(rule) != 1:
                raise GrantError(f"rule for {arg!r} must be one {{kind: value}} pair")
            kind, value = next(iter(rule.items()))
            if kind not in KINDS:
                raise GrantError(f"unknown rule kind {kind!r}; use one of {', '.join(KINDS)}")
            if kind == "any":
                if arg in WHERE_ARGS:
                    raise GrantError(f"'{arg}' decides where the action goes; give an exact rule, not 'any'")
                out[arg] = {"any": True}
            elif kind == "glob":
                if not isinstance(value, str):
                    raise GrantError("glob needs a text pattern")
                out[arg] = {"glob": self._abs_glob(value)}
            elif kind == "domain":
                d = str(value).strip().lower().rstrip(".")
                if "://" in d or "/" in d or "." not in d or "*" in d or not d.replace(".", "").replace("-", "").isalnum():
                    raise GrantError(f"domain must be a plain site name like example.com, not {value!r}")
                out[arg] = {"domain": d}
            elif kind == "max_chars":
                try:
                    n = int(value)
                except (TypeError, ValueError):
                    raise GrantError("max_chars needs a number")
                if not 1 <= n <= MAX_WRITE_CHARS:
                    raise GrantError(f"max_chars must be between 1 and {MAX_WRITE_CHARS}")
                out[arg] = {"max_chars": n}
            elif kind == "equals":
                if _plain(value) is None:
                    raise GrantError("equals needs a single value")
                out[arg] = {"equals": _plain(value)}
            elif kind == "one_of":
                if not isinstance(value, list) or not value or any(_plain(v) is None for v in value):
                    raise GrantError("one_of needs a list of values")
                out[arg] = {"one_of": [_plain(v) for v in value]}
            if arg in PATH_ARGS and kind not in ("glob", "equals", "one_of"):
                raise GrantError(f"'{arg}' is a file path: use a glob rule")
            if arg in PATH_ARGS and kind in ("equals", "one_of"):
                # exact files: stored as absolute paths inside the allowed folders
                vals = [value] if kind == "equals" else value
                if any(c in str(v) for v in vals for c in "*?["):
                    raise GrantError("use a glob rule for path patterns")
                out[arg] = {"one_of": [self._abs_glob(str(v)) for v in vals]}
            if arg == "url" and kind not in ("domain",):
                raise GrantError("'url' needs a domain rule")
        return out

    def create(self, tool: str, tier: str, constraints: dict, days: float, max_uses: int, note: str = "",
               created_by: str = "cli") -> Grant:
        if tier not in GRANTABLE_TIERS:
            raise GrantError(f"{tool} is {tier}: standing approvals are only for T1 and T2 tools, "
                             "never for send, pay, delete (T3) or prohibited (T4) actions")
        if created_by not in ("cli", "dashboard"):
            raise GrantError("grants are created only by Sachin (CLI or dashboard)")
        try:
            days = float(days)
            max_uses = int(max_uses)
        except (TypeError, ValueError):
            raise GrantError("days and max_uses must be numbers")
        if not 1 / 24 <= days <= MAX_DAYS:
            raise GrantError(f"expiry must be between 1 hour and {MAX_DAYS} days")
        if not 1 <= max_uses <= MAX_USES:
            raise GrantError(f"max uses must be between 1 and {MAX_USES}")
        rules = self._check_rules(constraints)
        now = self.clock()
        g = Grant("g-" + secrets.token_hex(4), tool, tier, rules, now, now + days * 86400, max_uses,
                  note=(note or "")[:200], created_by=created_by)
        self.conn.execute(
            """INSERT INTO standing_grants (id, tool, tier, constraints, created, expires, max_uses, note, created_by)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (g.id, g.tool, g.tier, json.dumps(rules, ensure_ascii=False), g.created, g.expires, g.max_uses,
             g.note, g.created_by))
        self.conn.commit()
        return g

    @staticmethod
    def _row(r) -> Grant:
        return Grant(r[0], r[1], r[2], json.loads(r[3]), r[4], r[5], r[6], r[7], bool(r[8]), r[9], r[10], r[11])

    _COLS = "id, tool, tier, constraints, created, expires, max_uses, uses, revoked, note, created_by, last_used"

    def get(self, grant_id: str) -> Grant | None:
        r = self.conn.execute(f"SELECT {self._COLS} FROM standing_grants WHERE id=?", (grant_id,)).fetchone()
        return self._row(r) if r else None

    def list(self, active_only: bool = False) -> list[Grant]:
        rows = self.conn.execute(f"SELECT {self._COLS} FROM standing_grants ORDER BY created DESC").fetchall()
        grants = [self._row(r) for r in rows]
        now = self.clock()
        return [g for g in grants if g.status(now) == "active"] if active_only else grants

    def revoke(self, grant_id: str) -> Grant:
        if not self.get(grant_id):
            raise KeyError(grant_id)
        self.conn.execute("UPDATE standing_grants SET revoked=1 WHERE id=?", (grant_id,))
        self.conn.commit()
        return self.get(grant_id)  # type: ignore[return-value]

    def uses(self, grant_id: str, limit: int = 100) -> list[dict]:
        rows = self.conn.execute(
            "SELECT ts, task_id, arguments FROM standing_grant_uses WHERE grant_id=? ORDER BY id DESC LIMIT ?",
            (grant_id, limit)).fetchall()
        return [{"ts": _iso(r[0]), "task_id": r[1], "arguments": json.loads(r[2])} for r in rows]

    # ---- matching ----

    def _path_ok(self, value: str, rule: dict) -> bool:
        if self.policy is None:
            return False
        try:
            path = self.policy.resolve(value)  # secrets and outside paths raise: never a match
        except (PathBlocked, PathDenied):
            return False
        if "glob" in rule:
            return _glob_match(rule["glob"], path.as_posix())
        return any(_norm(path.as_posix()) == _norm(p) for p in rule.get("one_of", []))

    def _arg_ok(self, arg: str, value, rule: dict) -> bool:
        kind, expected = next(iter(rule.items()))
        if kind == "any":
            return True
        text = _plain(value)
        if text is None:
            return False
        if arg in PATH_ARGS:
            return self._path_ok(text, rule)
        if kind == "glob":
            return self._path_ok(text, rule)
        if kind == "domain":
            host = _host(text)
            if host is None or suspicious_url(text):
                return False
            return host == expected or host.endswith("." + expected)
        if kind == "max_chars":
            return len(text) <= expected
        if kind == "equals":
            return text == expected
        if kind == "one_of":
            return text in expected
        return False

    def matches(self, g: Grant, tool: str, tier: str, arguments: dict) -> bool:
        if g.tool != tool or tier not in GRANTABLE_TIERS or g.status(self.clock()) != "active":
            return False
        if not isinstance(arguments, dict):
            return False
        for arg, value in arguments.items():
            rule = g.constraints.get(arg)
            if rule is None or not self._arg_ok(arg, value, rule):
                return False
        return True

    def find(self, tool: str, tier: str, arguments: dict) -> Grant | None:
        if tier not in GRANTABLE_TIERS:
            return None
        for g in self.list(active_only=True):
            if self.matches(g, tool, tier, arguments):
                return g
        return None

    def consume(self, g: Grant, task_id: str | None, arguments: dict) -> bool:
        """Count one use; False when the grant ran out or was revoked meanwhile (atomic)."""
        now = self.clock()
        cur = self.conn.execute(
            """UPDATE standing_grants SET uses = uses + 1, last_used = ?
               WHERE id = ? AND revoked = 0 AND uses < max_uses AND expires > ?""", (now, g.id, now))
        if cur.rowcount != 1:
            self.conn.commit()
            return False
        self.conn.execute("INSERT INTO standing_grant_uses (grant_id, ts, task_id, arguments) VALUES (?, ?, ?, ?)",
                          (g.id, now, task_id, json.dumps(arguments, ensure_ascii=False)[:4000]))
        self.conn.commit()
        return True


@dataclass
class SessionGrant:
    """A grouped low-risk approval: new files in one folder for the rest of this chat or task."""
    folder: Path
    task_id: str | None
    expires: float
    tools: frozenset[str] = field(default_factory=lambda: frozenset({"write_file"}))
