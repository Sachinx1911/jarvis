"""The Office page (PLAN.md 18.2 "Agent HQ" item 2, section 27): every loka (office) as rooms with its
teams, the Brain in the middle, "N agents · M running", and what waits for Sachin.

Every number here is read from tables and files (tasks, memory_index, tool_runs, model_usage, the
workspace YAML, profile/*.md). No model is called. Each optional source (skills, core memory, documents,
approvals, budgets) is wrapped so one missing piece never empties the page.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException

from jarvis.web.context import WebContext
from jarvis.workspaces.model import Team, Workspace, WorkspaceError
from jarvis.workspaces.store import WorkspaceStore

RUNNING_STATES = ("RUNNING", "VERIFYING")
WAITING_STATES = ("PAUSED", "WAITING_APPROVAL")
DONE_STATES = ("COMPLETED",)
FAILED_STATES = ("FAILED",)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _task_counts(tasks: list) -> dict[str, int]:
    out = {"done": 0, "running": 0, "waiting": 0, "failed": 0}
    for t in tasks:
        if t.state in DONE_STATES:
            out["done"] += 1
        elif t.state in RUNNING_STATES:
            out["running"] += 1
        elif t.state in WAITING_STATES:
            out["waiting"] += 1
        elif t.state in FAILED_STATES:
            out["failed"] += 1
    return out


def _by_state(tasks: list) -> dict[str, int]:
    out: dict[str, int] = {}
    for t in tasks:
        out[t.state] = out.get(t.state, 0) + 1
    return out


def _member_of(step: str | None, team: Team) -> str | None:
    """The member a running task's current step names, if any (the orchestrator writes member labels)."""
    if not step:
        return None
    low = step.lower()
    for m in team.members:
        if m.name.lower() in low:
            return m.name
    return None


def _running_now(tasks: list, team: Team) -> list[dict[str, Any]]:
    out = []
    for t in tasks:
        if t.state in RUNNING_STATES:
            d = {"task_id": t.id, "title": t.title, "current_step": t.current_step}
            who = _member_of(t.current_step, team)
            if who:
                d["member"] = who
            out.append(d)
    return out


def _last_run(tasks: list) -> str | None:
    stamps = [t.updated_at for t in tasks if t.updated_at]
    return max(stamps) if stamps else None


def _team_tasks(all_tasks: list, workspace: str, team: str) -> list:
    return [t for t in all_tasks if t.workspace == workspace and (t.plan or {}).get("team") == team]


def _skill_uses(conn) -> dict[str, int]:
    """How often each skill was loaded (tool_runs rows of the load_skill tool)."""
    uses: dict[str, int] = {}
    for (args,) in conn.execute("SELECT arguments FROM tool_runs WHERE tool='load_skill'"):
        try:
            name = (json.loads(args) if args else {}).get("name")
        except (json.JSONDecodeError, AttributeError):
            name = None
        if name:
            uses[name] = uses.get(name, 0) + 1
    return uses


def _skills(rt) -> list[dict[str, Any]]:
    try:
        uses = _skill_uses(rt.store.conn)
    except Exception:
        uses = {}
    try:
        index = rt.skills.index()
    except Exception:
        index = []
    out = [{"name": s.name, "uses": uses.get(s.name, 0)} for s in index]
    for name, n in uses.items():
        if name not in {s.name for s in index}:
            out.append({"name": name, "uses": n})
    return sorted(out, key=lambda s: (-s["uses"], s["name"]))


def _core_memory(rt) -> dict[str, Any]:
    out: dict[str, Any] = {"present": False, "files": [], "lines": 0, "chars": 0}
    for fname in ("USER.md", "MEMORY.md"):
        p = rt.paths.home / "profile" / fname
        try:
            if p.exists():
                text = p.read_text(encoding="utf-8")
                out["files"].append({"name": fname, "lines": text.count("\n") + (1 if text and not text.endswith("\n") else 0),
                                     "chars": len(text)})
        except OSError:
            continue
    out["present"] = bool(out["files"])
    out["lines"] = sum(f["lines"] for f in out["files"])
    out["chars"] = sum(f["chars"] for f in out["files"])
    return out


def _documents(rt) -> int:
    try:
        from jarvis.connectors.registry import ConnectorDeps, doc_library

        return len(doc_library(ConnectorDeps(rt.paths.home, rt.store, rt.audit, max_privacy="P2")).documents())
    except Exception:
        return 0


def _memories(conn, workspace: str | None = None) -> int:
    try:
        if workspace is None:
            return conn.execute("SELECT COUNT(*) FROM memory_index WHERE status='active'").fetchone()[0]
        return conn.execute("SELECT COUNT(*) FROM memory_index WHERE workspace=? AND status='active'",
                            (workspace,)).fetchone()[0]
    except Exception:
        return 0


def _today(conn, w: Workspace) -> dict[str, Any]:
    try:
        from jarvis.control.loka_budget import summary

        s = summary(conn, w.slug, w)
        return {"line": s["line"], "used": s["used"], "caps": s["caps"], "over": s.get("over")}
    except Exception:
        return {"line": "", "used": {}, "caps": {}, "over": None}


def _needs_regrant(conn, workspace: str) -> list[str]:
    try:
        from jarvis.control.astra import AstraStore

        return sorted({x["tool"] for x in AstraStore(conn).needs_regrant(workspace)})
    except Exception:
        return []


def _broker_pending(ctx: WebContext) -> list[dict[str, Any]]:
    """Approvals waiting in the dashboard broker (tasks and chats), each with its task_id."""
    try:
        return list(ctx.chats.broker.pending())
    except Exception:
        return []


def _scheduled_pending(conn) -> int:
    try:
        from jarvis.proactive.scheduler import PendingApprovals

        return len(PendingApprovals(conn).list())
    except Exception:
        return 0


def _tool_tiers(rt) -> dict[str, tuple[str, bool]]:
    try:
        from jarvis.web.data import tools_json

        return {t["name"]: (t["tier"], t["enabled"]) for t in tools_json(rt)["tools"]}
    except Exception:
        return {}


def team_room(team: Team, tasks: list) -> dict[str, Any]:
    return {"slug": team.slug, "name": team.name, "purpose": team.purpose, "colour": team.colour,
            "members": [{"name": m.name, "role": m.role, "profile": m.profile} for m in team.members],
            "tasks": _task_counts(tasks), "last_run": _last_run(tasks), "running_now": _running_now(tasks, team)}


def build_router(ctx: WebContext) -> APIRouter:
    r = APIRouter()

    def store(rt) -> WorkspaceStore:
        return WorkspaceStore(rt.paths.home)

    def all_tasks(rt) -> list:
        from jarvis.core.runtime import task_store

        return task_store(rt).list(include_final=True)

    @r.get("/office")
    def office() -> dict[str, Any]:
        with ctx.runtime() as rt:
            conn = rt.store.conn
            s = store(rt)
            workspaces = s.list(include_archived=True)
            tasks = all_tasks(rt)
            pending = _broker_pending(ctx)
            pending_task_ids = {p.get("task_id") for p in pending if p.get("task_id")}
            offices = []
            agents_total = 0
            for w in workspaces:
                w_tasks = [t for t in tasks if t.workspace == w.slug]
                try:
                    teams = s.teams(w.slug)
                except WorkspaceError:
                    teams = []
                rooms = []
                for t in teams:
                    t_tasks = _team_tasks(tasks, w.slug, t.slug)
                    room = team_room(t, t_tasks)
                    # waiting = PAUSED / WAITING_APPROVAL tasks, plus tasks with an approval open in the broker
                    extra = sum(1 for x in t_tasks if x.id in pending_task_ids and x.state not in WAITING_STATES)
                    room["tasks"]["waiting"] += extra
                    rooms.append(room)
                    if not w.archived:
                        agents_total += len(t.members)
                offices.append({
                    "slug": w.slug, "name": w.name, "kind": w.kind, "archived": w.archived, "brief": w.brief,
                    "language": w.language, "today": _today(conn, w), "needs_regrant": _needs_regrant(conn, w.slug),
                    "teams": rooms, "tasks_total": _by_state(w_tasks), "memories": _memories(conn, w.slug),
                })
            running = sum(1 for t in tasks if t.state in RUNNING_STATES)
            waiting_tasks = sum(1 for t in tasks if t.state in WAITING_STATES)
            return {
                "offices": offices,
                "brain": {"memories": _memories(conn), "documents": _documents(rt), "core_memory": _core_memory(rt),
                          "skills": _skills(rt)},
                "agents": {"total": agents_total, "running": running},
                "waiting": {"approvals": len(pending), "scheduled_approvals": _scheduled_pending(conn),
                            "needs_choice": 0, "tasks_waiting_approval": waiting_tasks},
                "ts": _now(),
            }

    @r.get("/office/{slug}/teams/{team}")
    def team_panel(slug: str, team: str) -> dict[str, Any]:
        with ctx.runtime() as rt:
            s = store(rt)
            try:
                w = s.get(slug)
                t = s.team(slug, team)
            except WorkspaceError as e:
                raise HTTPException(404, str(e))
            tasks = _team_tasks(all_tasks(rt), slug, team)
            room = team_room(t, tasks)
            recent = sorted(tasks, key=lambda x: x.updated_at or "", reverse=True)[:10]
            tiers = _tool_tiers(rt)
            tool_names = sorted({name for m in t.members for name in m.tools})
            tools = [{"name": n, "tier": tiers[n][0] if n in tiers else None,
                      "enabled": tiers[n][1] if n in tiers else None, "registered": n in tiers} for n in tool_names]
            uses = {}
            try:
                uses = _skill_uses(rt.store.conn)
            except Exception:
                pass
            running_by_member = {x.get("member"): x for x in room["running_now"] if x.get("member")}
            unassigned = [x for x in room["running_now"] if not x.get("member")]
            agents = []
            for m in t.members:
                busy = running_by_member.get(m.name)
                agents.append({"name": m.name, "role": m.role, "profile": m.profile, "brief": m.brief, "tools": list(m.tools),
                               "status": "running" if busy else "idle",
                               "current_step": busy["current_step"] if busy else None,
                               "task_id": busy["task_id"] if busy else None})
            return {
                "office": {"slug": w.slug, "name": w.name, "archived": w.archived},
                "team": {"slug": t.slug, "name": t.name, "purpose": t.purpose, "colour": t.colour,
                         "lead_brief": t.lead_brief, "archived": t.archived},
                "overview": {**room["tasks"], "total": len(tasks), "last_run": room["last_run"],
                             "members": len(t.members)},
                "agents": agents,
                "running_unassigned": unassigned,
                "tools": tools,
                "skills": [{"name": n, "uses": uses.get(n, 0)} for n in t.skills],
                "recent_tasks": [{"id": x.id, "title": x.title, "state": x.state, "updated_at": x.updated_at,
                                  "current_step": x.current_step, "team_label": (x.plan or {}).get("team_label")}
                                 for x in recent],
                "ts": _now(),
            }

    return r


__all__ = ["build_router", "team_room"]
