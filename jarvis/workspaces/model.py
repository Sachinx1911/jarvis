"""Workspaces and teams as data (PLAN.md 18.2, step 0).

A workspace is one office: Sachin's personal one (always present, slug "personal") or a company.
A team is a group of agents inside a workspace, built from the existing roles (researcher, writer,
checker, coder, operator) with its own briefs, tool subsets and skills. Both are YAML files under
data/workspaces/<slug>/ (private, never in git); this module only defines and validates them.

Validation here is deliberately plain: every error names the file field and what is allowed, so a
wrong file is reported and never crashes Jarvis.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

PERSONAL = "personal"
SHARED = "shared"  # a memory visible in every workspace
WORKSPACE_VERSION = 1
TEAM_VERSION = 1
KINDS = ("personal", "company")
ROLES = ("researcher", "writer", "checker", "coder", "operator")
LANGUAGES = ("en", "mr")
COLOURS = ("blue", "teal", "violet", "green", "amber", "red", "gray")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,31}$")
MAX_BRIEF = 1500
MAX_NAME = 60


class WorkspaceError(ValueError):
    """A workspace or team file is wrong; the message says which field and what is allowed."""


def check_slug(slug: Any, what: str = "slug") -> str:
    if not isinstance(slug, str) or not SLUG_RE.match(slug):
        raise WorkspaceError(f"{what} must be 2-32 lowercase letters, digits or dashes, not {slug!r}")
    return slug


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:32]
    if len(slug) < 2:
        raise WorkspaceError(f"cannot make a slug from {name!r}")
    return slug


@dataclass(frozen=True)
class Budget:
    """Per-day caps for a workspace's unattended work (same meaning as config/proactive.yaml)."""

    max_runs: int | None = None
    max_model_calls: int | None = None
    max_notional_usd: float | None = None


@dataclass(frozen=True)
class Workspace:
    slug: str
    name: str
    kind: str = "company"
    brief: str = ""
    language: str = "mr"
    projects: tuple[str, ...] = ()
    tools_allow: tuple[str, ...] = ()   # empty = every registered tool the role may use
    tools_deny: tuple[str, ...] = ()
    always_ask: tuple[str, ...] = ()    # tools that need approval in this workspace, whatever their tier
    budget: Budget = Budget()
    share_personal: bool = True         # personal memories are visible in this workspace
    archived: bool = False              # ended (law 2): hidden from lists, cannot be selected; never deleted
    version: int = WORKSPACE_VERSION

    @property
    def personal(self) -> bool:
        return self.slug == PERSONAL


@dataclass(frozen=True)
class Member:
    name: str
    role: str
    brief: str = ""
    tools: tuple[str, ...] = ()   # subset of the role's allowlist; empty = the role's full allowlist
    profile: str = ""             # worker profile from config/tasks.yaml; "" = the default


@dataclass(frozen=True)
class Team:
    slug: str
    name: str
    purpose: str = ""
    colour: str = "blue"
    lead_brief: str = ""
    members: tuple[Member, ...] = ()
    skills: tuple[str, ...] = ()
    archived: bool = False
    version: int = TEAM_VERSION


# ---- validation ----

def _str(data: dict, key: str, where: str, default: str | None = "", max_len: int = MAX_BRIEF) -> str:
    v = data.get(key, default)
    if v is None:
        v = ""
    if not isinstance(v, str):
        raise WorkspaceError(f"{where}: {key} must be text")
    if len(v) > max_len:
        raise WorkspaceError(f"{where}: {key} is longer than {max_len} characters")
    return v.strip()


def _names(data: dict, key: str, where: str) -> tuple[str, ...]:
    v = data.get(key) or []
    if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
        raise WorkspaceError(f"{where}: {key} must be a list of names")
    return tuple(dict.fromkeys(x.strip() for x in v if x.strip()))


def _choice(data: dict, key: str, allowed: tuple[str, ...], where: str, default: str) -> str:
    v = data.get(key, default)
    if v not in allowed:
        raise WorkspaceError(f"{where}: {key} must be one of {', '.join(allowed)}, not {v!r}")
    return v


def _flag(data: dict, key: str, where: str, default: bool = False) -> bool:
    v = data.get(key, default)
    if not isinstance(v, bool):
        raise WorkspaceError(f"{where}: {key} must be true or false")
    return v


def _version(data: dict, expected: int, where: str) -> int:
    v = data.get("version", 1)
    if not isinstance(v, int) or v < 1:
        raise WorkspaceError(f"{where}: version must be a whole number")
    if v > expected:
        raise WorkspaceError(f"{where}: version {v} is newer than this Jarvis understands ({expected}); update Jarvis")
    return v


def validate_workspace(data: Any, slug: str) -> Workspace:
    where = f"workspace {slug}"
    if not isinstance(data, dict):
        raise WorkspaceError(f"{where}: workspace.yaml must be a mapping")
    check_slug(slug, "workspace slug")
    version = _version(data, WORKSPACE_VERSION, where)
    kind = _choice(data, "kind", KINDS, where, "personal" if slug == PERSONAL else "company")
    if (slug == PERSONAL) != (kind == "personal"):
        raise WorkspaceError(f"{where}: only the 'personal' workspace may have kind personal")
    name = _str(data, "name", where, slug, MAX_NAME) or slug
    b = data.get("budget") or {}
    if not isinstance(b, dict):
        raise WorkspaceError(f"{where}: budget must be a mapping")
    for k in b:
        if k not in ("max_runs", "max_model_calls", "max_notional_usd"):
            raise WorkspaceError(f"{where}: budget.{k} is not a known cap (max_runs, max_model_calls, max_notional_usd)")
    try:
        budget = Budget(
            max_runs=None if b.get("max_runs") is None else int(b["max_runs"]),
            max_model_calls=None if b.get("max_model_calls") is None else int(b["max_model_calls"]),
            max_notional_usd=None if b.get("max_notional_usd") is None else float(b["max_notional_usd"]),
        )
    except (TypeError, ValueError):
        raise WorkspaceError(f"{where}: budget values must be numbers")
    tools = data.get("tools") or {}
    if not isinstance(tools, dict):
        raise WorkspaceError(f"{where}: tools must be a mapping with allow / deny lists")
    memory = data.get("memory") or {}
    if not isinstance(memory, dict):
        raise WorkspaceError(f"{where}: memory must be a mapping")
    share = memory.get("share_personal", True)
    if not isinstance(share, bool):
        raise WorkspaceError(f"{where}: memory.share_personal must be true or false")
    archived = _flag(data, "archived", where)
    if archived and slug == PERSONAL:
        raise WorkspaceError(f"{where}: the personal workspace cannot be archived")
    projects = _names(data, "projects", where)
    for pr in projects:
        if not re.match(r"^[a-z0-9-]{1,40}$", pr):
            raise WorkspaceError(f"{where}: project name {pr!r} is not a valid project slug")
    return Workspace(
        slug=slug, name=name, kind=kind, brief=_str(data, "brief", where),
        language=_choice(data, "language", LANGUAGES, where, "mr"), projects=projects,
        tools_allow=_names(tools, "allow", where), tools_deny=_names(tools, "deny", where),
        always_ask=_names(data, "always_ask", where), budget=budget, share_personal=share, archived=archived,
        version=version,
    )


def validate_team(data: Any, slug: str, role_tools: dict[str, frozenset[str]] | None = None) -> Team:
    """`role_tools` (role -> allowed tool names) lets a member's tool subset be checked against the
    role's allowlist, so a team file can narrow a role but never widen it."""
    where = f"team {slug}"
    if not isinstance(data, dict):
        raise WorkspaceError(f"{where}: the team file must be a mapping")
    check_slug(slug, "team slug")
    version = _version(data, TEAM_VERSION, where)
    name = _str(data, "name", where, slug, MAX_NAME) or slug
    lead = data.get("lead") or {}
    if not isinstance(lead, dict):
        raise WorkspaceError(f"{where}: lead must be a mapping with a brief")
    raw_members = data.get("members") or []
    if not isinstance(raw_members, list) or not raw_members:
        raise WorkspaceError(f"{where}: members must be a list with at least one member")
    members: list[Member] = []
    seen: set[str] = set()
    for i, m in enumerate(raw_members, 1):
        mw = f"{where}, member {i}"
        if not isinstance(m, dict):
            raise WorkspaceError(f"{mw}: must be a mapping")
        role = _choice(m, "role", ROLES, mw, "")
        mname = _str(m, "name", mw, role.title(), MAX_NAME) or role.title()
        if mname.lower() in seen:
            raise WorkspaceError(f"{mw}: the name {mname!r} is used twice")
        seen.add(mname.lower())
        tools = _names(m, "tools", mw)
        if tools and role_tools is not None:
            allowed = role_tools.get(role, frozenset())
            bad = [x for x in tools if x not in allowed]
            if bad:
                raise WorkspaceError(f"{mw}: {role} may not use {', '.join(bad)} (allowed: {', '.join(sorted(allowed))})")
        members.append(Member(name=mname, role=role, brief=_str(m, "brief", mw), tools=tools,
                              profile=_str(m, "profile", mw, "", 40)))
    return Team(
        slug=slug, name=name, purpose=_str(data, "purpose", where),
        colour=_choice(data, "colour", COLOURS, where, "blue"), lead_brief=_str(lead, "brief", where),
        members=tuple(members), skills=_names(data, "skills", where), archived=_flag(data, "archived", where),
        version=version,
    )


def workspace_to_dict(w: Workspace) -> dict[str, Any]:
    out: dict[str, Any] = {"version": w.version, "name": w.name, "kind": w.kind, "brief": w.brief,
                           "language": w.language, "projects": list(w.projects)}
    if w.tools_allow or w.tools_deny:
        out["tools"] = {"allow": list(w.tools_allow), "deny": list(w.tools_deny)}
    if w.always_ask:
        out["always_ask"] = list(w.always_ask)
    budget = {k: v for k, v in (("max_runs", w.budget.max_runs), ("max_model_calls", w.budget.max_model_calls),
                                ("max_notional_usd", w.budget.max_notional_usd)) if v is not None}
    if budget:
        out["budget"] = budget
    if not w.share_personal:
        out["memory"] = {"share_personal": False}
    if w.archived:
        out["archived"] = True
    return out


def team_to_dict(t: Team) -> dict[str, Any]:
    return {
        "version": t.version, "name": t.name, "purpose": t.purpose, "colour": t.colour,
        "lead": {"brief": t.lead_brief},
        "members": [{k: v for k, v in (("name", m.name), ("role", m.role), ("brief", m.brief),
                                       ("tools", list(m.tools)), ("profile", m.profile)) if v} for m in t.members],
        "skills": list(t.skills),
        **({"archived": True} if t.archived else {}),
    }
