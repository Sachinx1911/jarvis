"""Workspaces (offices) and their teams in the dashboard (PLAN.md 18.2 step 0, section 27).

Everything is a file under data/workspaces/<slug>/ and runs locally; no model is called here.
Ending a workspace or a team archives it (law 2): nothing is deleted. Every change is audit-logged.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from jarvis.web.context import WebContext
from jarvis.workspaces.model import PERSONAL, Team, Workspace, WorkspaceError, slugify
from jarvis.workspaces.store import WorkspaceStore


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=2, max_length=60)
    slug: str | None = Field(default=None, max_length=32)
    kind: Literal["company"] = "company"      # only the built-in "personal" workspace is personal
    brief: str = Field(default="", max_length=1500)
    language: Literal["en", "mr"] = "mr"


class WorkspaceEdit(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=60)
    brief: str | None = Field(default=None, max_length=1500)
    language: Literal["en", "mr"] | None = None
    duties: list[str] | None = None
    projects: list[str] | None = None
    share_personal: bool | None = None


class TeamAdd(BaseModel):
    template: str = Field(min_length=2, max_length=32)


def workspace_json(w: Workspace) -> dict[str, Any]:
    return {"slug": w.slug, "name": w.name, "kind": w.kind, "brief": w.brief, "language": w.language,
            "duties": list(w.duties), "projects": list(w.projects), "allies": list(w.allies),
            "tools": {"allow": list(w.tools_allow), "deny": list(w.tools_deny), "always_ask": list(w.always_ask)},
            "budget": {"max_runs": w.budget.max_runs, "max_model_calls": w.budget.max_model_calls,
                       "max_notional_usd": w.budget.max_notional_usd},
            "share_personal": w.share_personal, "archived": w.archived, "personal": w.personal}


def team_json(t: Team) -> dict[str, Any]:
    return {"slug": t.slug, "name": t.name, "purpose": t.purpose, "colour": t.colour, "lead_brief": t.lead_brief,
            "members": [{"name": m.name, "role": m.role, "brief": m.brief, "tools": list(m.tools),
                         "profile": m.profile} for m in t.members],
            "skills": list(t.skills), "archived": t.archived}


def build_router(ctx: WebContext) -> APIRouter:
    r = APIRouter()

    def store(rt) -> WorkspaceStore:
        return WorkspaceStore(rt.paths.home)

    def bad(e: WorkspaceError) -> HTTPException:
        text = str(e)
        return HTTPException(404 if text.startswith("no workspace") or text.startswith("no team") else 400, text)

    @r.get("/workspaces")
    def workspaces(archived: bool = False) -> dict[str, Any]:
        with ctx.runtime() as rt:
            s = store(rt)
            items = [workspace_json(w) for w in s.list(include_archived=archived)]
            return {"items": items, "problems": [{"path": p.path, "error": p.error} for p in s.problems]}

    @r.post("/workspaces")
    def workspace_create(body: WorkspaceCreate) -> dict[str, Any]:
        with ctx.runtime() as rt:
            try:
                slug = body.slug or slugify(body.name)
                w = store(rt).create(slug, body.name.strip(), body.kind, body.brief.strip(), body.language)
            except WorkspaceError as e:
                raise bad(e)
            rt.audit.write("workspace_created", source="dashboard", workspace=w.slug)
            return workspace_json(w)

    @r.get("/workspaces/{slug}")
    def workspace_show(slug: str) -> dict[str, Any]:
        with ctx.runtime() as rt:
            s = store(rt)
            try:
                w = s.get(slug)
                teams = [team_json(t) for t in s.teams(slug, include_archived=True)]
            except WorkspaceError as e:
                raise bad(e)
            return {**workspace_json(w), "teams": teams,
                    "problems": [{"path": p.path, "error": p.error} for p in s.problems]}

    @r.put("/workspaces/{slug}")
    def workspace_edit(slug: str, body: WorkspaceEdit) -> dict[str, Any]:
        from dataclasses import replace

        with ctx.runtime() as rt:
            s = store(rt)
            try:
                w = s.get(slug)
                changes: dict[str, Any] = {}
                if body.name is not None:
                    changes["name"] = body.name.strip()
                if body.brief is not None:
                    changes["brief"] = body.brief.strip()
                if body.language is not None:
                    changes["language"] = body.language
                if body.duties is not None:
                    changes["duties"] = tuple(d.strip() for d in body.duties if d.strip())
                if body.projects is not None:
                    changes["projects"] = tuple(p.strip() for p in body.projects if p.strip())
                if body.share_personal is not None:
                    changes["share_personal"] = body.share_personal
                w = s.save(replace(w, **changes))
            except WorkspaceError as e:
                raise bad(e)
            rt.audit.write("workspace_edited", source="dashboard", workspace=slug, fields=sorted(changes))
            return workspace_json(w)

    @r.post("/workspaces/{slug}/archive")
    def workspace_archive(slug: str) -> dict[str, Any]:
        with ctx.runtime() as rt:
            try:
                w = store(rt).archive(slug)
            except WorkspaceError as e:
                raise bad(e)
            rt.audit.write("workspace_archived", source="dashboard", workspace=slug)
            return workspace_json(w)

    @r.post("/workspaces/{slug}/unarchive")
    def workspace_unarchive(slug: str) -> dict[str, Any]:
        with ctx.runtime() as rt:
            try:
                w = store(rt).unarchive(slug)
            except WorkspaceError as e:
                raise bad(e)
            rt.audit.write("workspace_unarchived", source="dashboard", workspace=slug)
            return workspace_json(w)

    @r.get("/workspaces/{slug}/teams")
    def teams(slug: str, archived: bool = False) -> dict[str, Any]:
        with ctx.runtime() as rt:
            s = store(rt)
            try:
                items = [team_json(t) for t in s.teams(slug, include_archived=archived)]
            except WorkspaceError as e:
                raise bad(e)
            return {"items": items, "templates": [team_json(t) for t in s.templates()],
                    "problems": [{"path": p.path, "error": p.error} for p in s.problems]}

    @r.post("/workspaces/{slug}/teams")
    def team_add(slug: str, body: TeamAdd) -> dict[str, Any]:
        with ctx.runtime() as rt:
            try:
                t = store(rt).add_team(slug, template=body.template)
            except WorkspaceError as e:
                raise bad(e)
            rt.audit.write("team_added", source="dashboard", workspace=slug, team=t.slug, template=body.template)
            return team_json(t)

    @r.post("/workspaces/{slug}/teams/{team}/archive")
    def team_archive(slug: str, team: str) -> dict[str, Any]:
        with ctx.runtime() as rt:
            try:
                t = store(rt).archive_team(slug, team)
            except WorkspaceError as e:
                raise bad(e)
            rt.audit.write("team_archived", source="dashboard", workspace=slug, team=team)
            return team_json(t)

    @r.post("/workspaces/{slug}/teams/{team}/unarchive")
    def team_unarchive(slug: str, team: str) -> dict[str, Any]:
        with ctx.runtime() as rt:
            try:
                t = store(rt).unarchive_team(slug, team)
            except WorkspaceError as e:
                raise bad(e)
            rt.audit.write("team_unarchived", source="dashboard", workspace=slug, team=team)
            return team_json(t)

    @r.get("/workspaces/{slug}/stats")
    def workspace_stats(slug: str) -> dict[str, Any]:
        """Live counts for the Office page: memories, tasks by state, model calls today."""
        with ctx.runtime() as rt:
            try:
                store(rt).get(slug)
            except WorkspaceError as e:
                raise bad(e)
            conn = rt.store.conn
            mem = conn.execute("SELECT COUNT(*) FROM memory_index WHERE workspace=? AND status='active'", (slug,)).fetchone()[0]
            tasks = {state: n for state, n in conn.execute(
                "SELECT state, COUNT(*) FROM tasks WHERE workspace=? GROUP BY state", (slug,))}
            calls = conn.execute("SELECT COUNT(*), COALESCE(SUM(notional_usd), 0) FROM model_usage "
                                 "WHERE workspace=? AND date(ts)=date('now')", (slug,)).fetchone()
            return {"slug": slug, "memories": mem, "tasks": tasks,
                    "today": {"model_calls": calls[0], "notional_usd": round(calls[1] or 0.0, 4)}}

    return r


__all__ = ["build_router", "workspace_json", "team_json", "PERSONAL"]
