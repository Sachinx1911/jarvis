"""Schedules, reminders, unattended approvals and the morning brief in the dashboard.

Uses the public Proactive object (jarvis/proactive/service.py) and its stores; nothing in
jarvis/proactive is changed. A schedule is saved only after an explicit confirm: the
parsed draft is kept on the server under a random id, shown to Sachin, and only the
confirm call with that id saves exactly what was shown.
"""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import asdict
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from jarvis.web.approvals import args_hash
from jarvis.web.context import WebContext
from jarvis.web.jobs import JobBusy

DRAFT_TTL_S = 15 * 60
MAX_DRAFTS = 20


class DraftBody(BaseModel):
    text: str = Field(default="", max_length=1000)
    kind: Literal["prompt", "skill", "agent", "brief", "heartbeat"] = "prompt"
    target: str = Field(default="", max_length=80)
    output: Literal["telegram", "file", "both"] | None = None
    use_model: bool = True


class ConfirmBody(BaseModel):
    draft_id: str = Field(min_length=8, max_length=64)


class ReminderBody(BaseModel):
    text: str = Field(min_length=1, max_length=500)


class Decision(BaseModel):
    decision: Literal["approve", "deny"]
    args_sha256: str = ""


def _schedule_json(s, runs: list | None = None) -> dict[str, Any]:
    d = asdict(s)
    if runs is not None:
        d["runs"] = runs
    return d


def build_router(ctx: WebContext) -> APIRouter:
    r = APIRouter()
    drafts: dict[str, tuple[float, Any]] = {}
    lock = threading.Lock()

    def keep_draft(draft) -> str:
        now = time.time()
        with lock:
            for k in [k for k, (t, _) in drafts.items() if now - t > DRAFT_TTL_S]:
                drafts.pop(k, None)
            while len(drafts) >= MAX_DRAFTS:
                drafts.pop(min(drafts, key=lambda k: drafts[k][0]))
            did = secrets.token_hex(12)
            drafts[did] = (now, draft)
        return did

    def schedule_store(rt):
        from jarvis.proactive.scheduler import ScheduleStore

        return ScheduleStore(rt.store.conn)

    def need(rt, sid: str):
        s = schedule_store(rt).get(sid)
        if s is None:
            raise HTTPException(404, "no such schedule")
        return s

    # ---- schedules ----

    @r.get("/schedules/all")
    def schedules_all() -> dict[str, Any]:
        from jarvis.proactive.scheduler import PendingApprovals

        with ctx.runtime() as rt:
            items = [_schedule_json(s) for s in schedule_store(rt).list()]
            pending = len(PendingApprovals(rt.store.conn).list())
        return {"items": items, "pending_approvals": pending,
                "running_here": bool(ctx.extra.get("scheduler_running")),
                "job": ctx.jobs.get("schedule-run")}

    @r.post("/schedules/draft")
    def schedule_draft(body: DraftBody) -> dict[str, Any]:
        """Read the text into a draft. Nothing is saved here."""
        from jarvis.proactive.schedule_parse import ScheduleDraft, ScheduleParseError

        p = ctx.proactive()
        text = body.text.strip()
        if not text and body.kind not in ("brief", "heartbeat"):
            raise HTTPException(400, "say what and when, e.g. 'every Monday at 9 project summary'")
        if body.kind in ("skill", "agent") and not body.target.strip():
            raise HTTPException(400, f"a {body.kind} schedule needs a {body.kind} name")
        if body.use_model and ctx.stop.engaged():
            raise HTTPException(409, "emergency stop is on")
        defaults: dict[str, Any] = {"kind": body.kind, "target": body.target.strip(),
                                    "output": body.output or p.default_output}
        try:
            draft: ScheduleDraft = p.draft(text, defaults, use_model=body.use_model)
        except ScheduleParseError as e:
            return {"draft_id": None, "question": e.question}
        did = keep_draft(draft)
        ctx.audit.write("schedule_drafted", source="dashboard", kind=draft.kind, cron=draft.cron, read_by=draft.source)
        return {"draft_id": did, "draft": asdict(draft), "show": draft.show(p.now())}

    @r.post("/schedules/confirm")
    def schedule_confirm(body: ConfirmBody) -> dict[str, Any]:
        with lock:
            item = drafts.pop(body.draft_id, None)
        if item is None or time.time() - item[0] > DRAFT_TTL_S:
            raise HTTPException(404, "this draft expired or was already saved; read the text again")
        p = ctx.proactive()
        try:
            s = p.save(item[1], "dashboard")
        except ValueError as e:
            raise HTTPException(400, f"not saved: {e}")
        return {"saved": _schedule_json(s)}

    @r.post("/schedules/{sid}/{action}")
    def schedule_action(sid: str, action: Literal["pause", "resume", "delete", "run-now"]) -> dict[str, Any]:
        p = ctx.proactive()
        with ctx.runtime() as rt:
            need(rt, sid)
            store = schedule_store(rt)
            if action == "delete":
                store.delete(sid)
            elif action in ("pause", "resume"):
                store.set_enabled(sid, action == "resume", p.now())
            rt.audit.write(f"schedule_{action.replace('-', '_')}", schedule_id=sid, source="dashboard")
        if action == "run-now":
            if ctx.stop.engaged():
                raise HTTPException(409, "emergency stop is on")

            def run() -> dict[str, Any]:
                res = p.runner().run(sid, "run-now")
                return {"schedule_id": sid, "status": res.status, "text": (res.text or "")[:4000]}

            try:
                ctx.jobs.start("schedule-run", run, key=sid)
            except JobBusy as e:
                raise HTTPException(409, str(e))
            return {"id": sid, "started": True}
        return {"id": sid, "done": action}

    @r.get("/schedules/{sid}/runs")
    def schedule_runs(sid: str) -> dict[str, Any]:
        with ctx.runtime() as rt:
            s = need(rt, sid)
            return _schedule_json(s, schedule_store(rt).runs(sid, 20))

    # ---- approvals queued by unattended runs ----

    @r.get("/unattended")
    def unattended() -> dict[str, Any]:
        from jarvis.proactive.scheduler import PendingApprovals

        with ctx.runtime() as rt:
            items = PendingApprovals(rt.store.conn).list()
        return {"items": [{**a, "args_sha256": args_hash(a["arguments"])} for a in items]}

    @r.post("/unattended/{pid}")
    def unattended_answer(pid: int, body: Decision) -> dict[str, Any]:
        from jarvis.proactive.scheduler import PendingApprovals

        with ctx.runtime() as rt:
            item = PendingApprovals(rt.store.conn).get(pid)
        if item is None:
            raise HTTPException(404, "no such pending approval")
        if item["status"] != "pending":
            raise HTTPException(409, f"#{pid} is already {item['status']}")
        p = ctx.proactive()
        if body.decision == "deny":
            res = p.deny_pending(pid, "dashboard")
        else:
            if body.args_sha256 != args_hash(item["arguments"]):
                raise HTTPException(409, "the arguments shown do not match the stored call; reload and check again")
            res = p.approve_pending(pid, "dashboard")
        return {"id": pid, "status": res.status, "message": res.message}

    # ---- reminders ----

    @r.get("/reminders")
    def reminders() -> dict[str, Any]:
        from jarvis.proactive.reminders import ReminderStore

        with ctx.runtime() as rt:
            items = ReminderStore(rt.store.conn).pending()
        return {"items": [{"id": x.id, "text": x.text, "due_at": x.due_at.isoformat(), "status": x.status}
                          for x in items]}

    @r.post("/reminders")
    def reminder_add(body: ReminderBody) -> dict[str, Any]:
        from jarvis.proactive.reminders import ReminderStore, parse_reminder

        p = ctx.proactive()
        parsed = parse_reminder(body.text, p.now())
        if not parsed:
            raise HTTPException(400, "I could not read when. Try: 'in 10 minutes call back', "
                                     "'tomorrow at 9 pay rent', 'udya sakali 8 la doctor'.")
        with ctx.runtime() as rt:
            rem = ReminderStore(rt.store.conn, rt.audit).add(parsed.text, parsed.due, "dashboard", p.now())
        return {"id": rem.id, "text": rem.text, "due_at": rem.due_at.isoformat(),
                "running_here": bool(ctx.extra.get("scheduler_running"))}

    @r.post("/reminders/{rid}/cancel")
    def reminder_cancel(rid: int) -> dict[str, Any]:
        from jarvis.proactive.reminders import ReminderStore

        with ctx.runtime() as rt:
            ok = ReminderStore(rt.store.conn).cancel(rid)
            if not ok:
                raise HTTPException(404, "no pending reminder with that number")
            rt.audit.write("reminder_cancelled", reminder_id=rid, source="dashboard")
        return {"id": rid, "cancelled": True}

    # ---- morning brief ----

    @r.get("/brief")
    def brief() -> dict[str, Any]:
        p = ctx.proactive()
        text = p.brief_text()
        ctx.audit.write("brief_shown", source="dashboard", chars=len(text))
        return {"text": text}

    return r
