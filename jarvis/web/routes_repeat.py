"""Repeat-this in the dashboard (jarvis/tasks/repeat.py; PROGRESS.md decisions on repeat-this).

A finished task becomes a skill + schedule through the same propose/confirm flow as chat,
Telegram and `jarvis task repeat`, with channel "dashboard". Nothing in jarvis/tasks is
changed and the rules stay where they are: the 30-minute minimum interval, the 1-hour
expiry of a draft and the unattended T0/T1 rule are enforced by repeat.py and the scheduler.

Saving is bound to the exact draft on screen: every draft is shown with the SHA-256 of its
id, skill text and schedule, and Save must send that hash back for that proposal id. A draft
made in chat or on Telegram can be opened, saved or cancelled here too (the same pending
store); Telegram never received the full text, the dashboard on this computer shows it.
"""

from __future__ import annotations

import re
import time
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from jarvis.web.approvals import args_hash
from jarvis.web.context import WebContext

PROPOSAL_ID = re.compile(r"^rp-[0-9a-f]{6}$")


class ProposeBody(BaseModel):
    task_id: str = Field(pattern=r"^t-\d{1,6}$")
    when: str = Field(min_length=1, max_length=200)


class SaveBody(BaseModel):
    draft_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def draft_hash(p) -> str:
    """What the Save click refers to: the proposal id, its source, the skill text and the schedule."""
    return args_hash({"id": p.id, "source": p.source, "when": p.when, "skill_text": p.skill_text,
                      "schedule": p.schedule})


def _expires_in(p, ttl_s: float) -> int:
    return max(0, int(float(p.created_ts or 0) + ttl_s - time.time()))


def _origin(source: str) -> str:
    return "task" if source.startswith("task ") else "chat" if source.startswith("chat ") else "other"


def build_router(ctx: WebContext) -> APIRouter:
    r = APIRouter()

    def store(rt):
        from jarvis.tasks.repeat import RepeatStore

        return RepeatStore(rt.paths.data)

    def need(rt, pid: str):
        if not PROPOSAL_ID.match(pid):
            raise HTTPException(400, "invalid draft id")
        p = store(rt).get(pid)   # an expired draft is removed here and comes back as None
        if p is None:
            raise HTTPException(404, "this draft expired (drafts last 1 hour) or was already answered; "
                                     "nothing was saved")
        return p

    def summary(p, ttl_s: float) -> dict[str, Any]:
        return {"id": p.id, "source": p.source, "origin": _origin(p.source), "goal": p.goal[:120],
                "when": p.when, "skill": p.skill, "cron": p.schedule.get("cron", ""),
                "description": p.schedule.get("description", ""), "created_at": p.created_at,
                "expires_in_s": _expires_in(p, ttl_s)}

    def full(rt, p, proactive) -> dict[str, Any]:
        from jarvis.tasks.repeat import unattended_steps

        skills_dir = rt.paths.home / "skills"
        try:
            show = p.show(proactive.now(), skills_dir)
        except Exception as e:  # a broken schedule must still be visible (Save will refuse it)
            show = f"(could not show this draft: {type(e).__name__}: {e})"
        return {**summary(p, store(rt).ttl_s), "goal": p.goal, "skill_text": p.skill_text,
                "schedule": dict(p.schedule), "held_steps": unattended_steps(p.skill_text),
                "skill_exists": (skills_dir / p.skill / "SKILL.md").exists(), "show": show,
                "draft_sha256": draft_hash(p)}

    @r.get("/repeat/drafts")
    def drafts() -> dict[str, Any]:
        """Drafts waiting for a yes, from any channel (chat, Telegram, here). Expired ones are removed."""
        from jarvis.tasks.repeat import MIN_INTERVAL_MINUTES

        p = ctx.proactive()
        with ctx.runtime() as rt:
            s = store(rt)
            items = []
            for path in sorted(s.pending_dir.glob("rp-*.json")):
                prop = s.get(path.stem)
                if prop is not None:
                    items.append(summary(prop, s.ttl_s))
            ttl = s.ttl_s
        items.sort(key=lambda x: x["created_at"], reverse=True)
        limit = float(p.settings.section("schedules").get("repeat_min_interval_minutes", MIN_INTERVAL_MINUTES))
        return {"items": items, "ttl_s": ttl, "min_interval_minutes": limit}

    @r.get("/repeat/drafts/{pid}")
    def draft_show(pid: str) -> dict[str, Any]:
        p = ctx.proactive()
        with ctx.runtime() as rt:
            return full(rt, need(rt, pid), p)

    @r.post("/repeat/propose")
    def propose(body: ProposeBody) -> dict[str, Any]:
        """Read the time, then draft the skill (one model call through the skill_draft route).
        Only a pending draft is stored; nothing is saved here."""
        from jarvis.core.runtime import task_store
        from jarvis.providers.base import ProviderError
        from jarvis.routing.policy import RoutingError
        from jarvis.tasks.repeat import RepeatError, propose as make_proposal

        if ctx.stop.engaged():
            raise HTTPException(409, "emergency stop is on; nothing is drafted until it is released")
        p = ctx.proactive()
        with ctx.runtime() as rt:
            if task_store(rt).get(body.task_id) is None:
                raise HTTPException(404, "no such task")
            try:
                proposal = make_proposal(rt, p, body.when.strip(), task_id=body.task_id, channel="dashboard")
            except RepeatError as e:
                raise HTTPException(400, str(e))
            except RoutingError as e:
                raise HTTPException(400, f"routing error: {e}")
            except ProviderError as e:
                raise HTTPException(502, f"model error ({e.kind}): {e}")
            rt.audit.write("repeat_proposed", source="dashboard", proposal=proposal.id, task_id=body.task_id)
            return full(rt, proposal, p)

    @r.post("/repeat/drafts/{pid}/save")
    def save(pid: str, body: SaveBody) -> dict[str, Any]:
        """The explicit Save click on one shown draft: saves its skill and schedule."""
        from jarvis.tasks.repeat import confirm

        p = ctx.proactive()
        with ctx.runtime() as rt:
            prop = need(rt, pid)
            if body.draft_sha256 != draft_hash(prop):
                rt.audit.write("repeat_save_refused", source="dashboard", proposal=pid, reason="draft_changed")
                raise HTTPException(409, "this draft is not the one on screen; open it again and check it")
            message = confirm(rt, p, pid, True, channel="dashboard")
            if not message.startswith("Saved"):
                reason = "expired" if message.startswith("That draft expired") else "refused"
                rt.audit.write("repeat_save_refused", source="dashboard", proposal=pid, reason=reason)
                raise HTTPException(404 if reason == "expired" else 400, message)
            entry = next((e for e in reversed(store(rt).saved()) if e.get("proposal") == pid), {})
            rt.audit.write("repeat_saved", source="dashboard", proposal=pid, schedule_id=entry.get("schedule_id"))
        return {"saved": True, "id": pid, "skill": prop.skill, "schedule_id": entry.get("schedule_id"),
                "message": message, "running_here": bool(ctx.extra.get("scheduler_running"))}

    @r.post("/repeat/drafts/{pid}/cancel")
    def cancel(pid: str) -> dict[str, Any]:
        from jarvis.tasks.repeat import confirm

        p = ctx.proactive()
        with ctx.runtime() as rt:
            need(rt, pid)
            message = confirm(rt, p, pid, False, channel="dashboard")
            rt.audit.write("repeat_cancelled", source="dashboard", proposal=pid)
        return {"cancelled": True, "id": pid, "message": message}

    return r
