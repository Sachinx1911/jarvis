"""Teach by demonstration in the dashboard (PLAN.md section 8): start/stop a recording,
add notes, show the evidence, draft a skill (one model call through the existing
skill_draft route), edit the draft, approve it (old versions are kept), list skills.

Running a skill goes through the dashboard chat, so the normal approvals apply.
"""

from __future__ import annotations

import json
import re
from typing import Any

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from jarvis.web.context import WebContext

RID = re.compile(r"^r-[0-9a-f]{6}$")
SKILL_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
MAX_DRAFT = 60_000


class StartBody(BaseModel):
    name: str = Field(default="demo", max_length=80)


class NoteBody(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class DraftText(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_DRAFT)


def _frontmatter(text: str) -> dict[str, Any] | None:
    m = re.match(r"^---\n(.*?)\n---", text.replace("\r\n", "\n"), re.DOTALL)
    if not m:
        return None
    try:
        data = yaml.safe_load(m.group(1))
    except yaml.YAMLError:
        return None
    return data if isinstance(data, dict) else None


def build_router(ctx: WebContext) -> APIRouter:
    r = APIRouter()

    def recorder(rt):
        from jarvis.cli_tasks import recorder as make_recorder

        return make_recorder(rt)

    def folder(rt, rid: str):
        if not RID.match(rid):
            raise HTTPException(400, "invalid recording id")
        path = rt.paths.data / "recordings" / rid
        if not (path / "meta.json").exists():
            raise HTTPException(404, "no such recording")
        return path

    def recordings(rt) -> list[dict[str, Any]]:
        root = rt.paths.data / "recordings"
        out = []
        for meta_file in sorted(root.glob("r-*/meta.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            f = meta_file.parent
            out.append({"id": meta.get("id"), "name": meta.get("name"), "status": meta.get("status"),
                        "started_at": meta.get("started_at"), "notes": meta.get("notes", []),
                        "has_evidence": (f / "evidence.md").exists(), "has_draft": (f / "SKILL.draft.md").exists()})
        return out[:50]

    def skills(rt) -> list[dict[str, Any]]:
        out = []
        for s in rt.skills.index():
            meta = _frontmatter(s.path.read_text(encoding="utf-8")) or {}
            versions = sorted(p.name for p in s.path.parent.glob("SKILL.v*.md"))
            out.append({"name": s.name, "description": s.description, "version": meta.get("version"),
                        "source": meta.get("source"), "old_versions": versions})
        return out

    @r.get("/teach")
    def teach() -> dict[str, Any]:
        with ctx.runtime() as rt:
            active = recorder(rt).active()
            return {"active": {"id": active.id, "name": active.name, "started_at": active.meta.get("started_at"),
                               "notes": active.meta.get("notes", [])} if active else None,
                    "recordings": recordings(rt), "skills": skills(rt)}

    @r.post("/teach/start")
    def start(body: StartBody) -> dict[str, Any]:
        with ctx.runtime() as rt:
            try:
                rec = recorder(rt).start(body.name.strip() or "demo")
            except RuntimeError as e:
                raise HTTPException(409, str(e))
            rt.audit.write("recording_started", source="dashboard", recording=rec.id)
            return {"id": rec.id, "name": rec.name,
                    "hint": "Now do the task in the Chat tab. Add notes on why you do each step."}

    @r.post("/teach/note")
    def note(body: NoteBody) -> dict[str, Any]:
        with ctx.runtime() as rt:
            try:
                recorder(rt).note(body.text)
            except RuntimeError as e:
                raise HTTPException(409, str(e))
            rt.audit.write("recording_note", source="dashboard", chars=len(body.text))
            return {"noted": True}

    @r.post("/teach/stop")
    def stop() -> dict[str, Any]:
        with ctx.runtime() as rt:
            try:
                rec, evidence = recorder(rt).stop()
            except RuntimeError as e:
                raise HTTPException(409, str(e))
            rt.audit.write("recording_stopped", source="dashboard", recording=rec.id)
            return {"id": rec.id, "evidence": evidence}

    @r.get("/teach/recordings/{rid}")
    def show(rid: str) -> dict[str, Any]:
        with ctx.runtime() as rt:
            f = folder(rt, rid)
            meta = json.loads((f / "meta.json").read_text(encoding="utf-8"))
            meta.pop("snapshot", None)
            ev, dr = f / "evidence.md", f / "SKILL.draft.md"
            return {"id": rid, "meta": meta, "evidence": ev.read_text(encoding="utf-8") if ev.exists() else None,
                    "draft": dr.read_text(encoding="utf-8") if dr.exists() else None}

    @r.post("/teach/recordings/{rid}/draft")
    def draft(rid: str) -> dict[str, Any]:
        """One model call through the skill_draft route (provider layer, routing policy)."""
        from jarvis.core.runtime import make_chat
        from jarvis.providers import make_provider
        from jarvis.providers.base import ProviderError
        from jarvis.routing.policy import RoutingError, decide

        if ctx.stop.engaged():
            raise HTTPException(409, "emergency stop is on")
        with ctx.runtime() as rt:
            f = folder(rt, rid)
            if not (f / "evidence.md").exists():
                raise HTTPException(409, "stop the recording first")
            try:
                d = decide(rt.config, "skill_draft", ctx.settings.provider)
            except RoutingError as e:
                raise HTTPException(400, f"routing error: {e}")
            tiers = {t.spec.name: t.tier for t in make_chat(rt, "fake").tools.all()}
            try:
                path = recorder(rt).draft(rid, make_provider(d.provider, rt.config), d, tiers)
            except ProviderError as e:
                raise HTTPException(502, f"model error ({e.kind}): {e}")
            except ValueError as e:
                raise HTTPException(502, str(e))
            rt.audit.write("skill_drafted", source="dashboard", recording=rid, provider=d.provider, model=d.model)
            return {"id": rid, "draft": path.read_text(encoding="utf-8")}

    @r.put("/teach/recordings/{rid}/draft")
    def edit_draft(rid: str, body: DraftText) -> dict[str, Any]:
        text = body.text.replace("\r\n", "\n")
        meta = _frontmatter(text)
        if not meta or not str(meta.get("name") or "").strip():
            raise HTTPException(400, "the draft must start with a --- front matter block that has a name")
        with ctx.runtime() as rt:
            f = folder(rt, rid)
            (f / "SKILL.draft.md").write_text(text, encoding="utf-8")
            rt.audit.write("skill_draft_edited", source="dashboard", recording=rid, chars=len(text))
            return {"id": rid, "saved": True}

    @r.post("/teach/recordings/{rid}/approve")
    def approve(rid: str) -> dict[str, Any]:
        with ctx.runtime() as rt:
            f = folder(rt, rid)
            if not (f / "SKILL.draft.md").exists():
                raise HTTPException(409, "no draft yet")
            try:
                path = recorder(rt).approve(rid, rt.paths.home / "skills")
            except (FileNotFoundError, ValueError, AttributeError, KeyError, TypeError) as e:
                raise HTTPException(400, f"cannot approve this draft: {e}")
            rt.audit.write("skill_approved", source="dashboard", recording=rid, path=str(path))
            meta = _frontmatter(path.read_text(encoding="utf-8")) or {}
            return {"skill": path.parent.name, "version": meta.get("version")}

    @r.get("/skills/{name}")
    def skill_show(name: str) -> dict[str, Any]:
        if not SKILL_NAME.match(name):
            raise HTTPException(400, "invalid skill name")
        with ctx.runtime() as rt:
            text = rt.skills.load(name)
            if text is None:
                raise HTTPException(404, "no such skill")
            return {"name": name, "text": text}

    return r
