"""Schedules, event triggers, reminders, unattended approvals and the morning brief in the dashboard.

Uses the public Proactive object (jarvis/proactive/service.py) and its stores; nothing in
jarvis/proactive is changed. A schedule or a trigger is saved only after an explicit
confirm: the parsed draft is kept on the server under a random id, shown to Sachin, and
only the confirm call with that id saves exactly what was shown. Deleting a trigger needs
its id sent back as the confirmation. An email trigger's sender and subject are P2 until
decision #19, so they are never sent back to the browser (not in drafts, the list or runs).
"""

from __future__ import annotations

import re
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
TRIGGER_ID = re.compile(r"^t-\d{3,}$")


class DraftBody(BaseModel):
    text: str = Field(default="", max_length=1000)
    kind: Literal["prompt", "skill", "agent", "brief", "heartbeat"] = "prompt"
    target: str = Field(default="", max_length=80)
    output: Literal["telegram", "file", "both"] | None = None
    use_model: bool = True


class ConfirmBody(BaseModel):
    draft_id: str = Field(min_length=8, max_length=64)


class TriggerDraftBody(BaseModel):
    text: str = Field(default="", max_length=1000)
    kind: Literal["notify", "prompt", "skill", "agent"] | None = None   # default: read from the sentence
    target: str = Field(default="", max_length=80)
    output: Literal["telegram", "file", "both"] | None = None
    every_minutes: float | None = Field(default=None, ge=1, le=7 * 24 * 60)
    cooldown_minutes: float | None = Field(default=None, ge=0, le=7 * 24 * 60)


class TriggerDeleteBody(BaseModel):
    confirm: str = Field(min_length=1, max_length=20)   # the trigger id, sent back from the confirm step


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


HIDDEN = "[hidden: P2]"


def _private_bits(d) -> list[str]:
    """The parts of a trigger draft that must not go back to the browser: an email rule's
    sender and subject (P2 until decision #19)."""
    if d.source != "email_from":
        return []
    return [str(v) for v in (d.condition.get("sender"), d.condition.get("subject")) if v]


def _hide(text: str, bits: list[str]) -> str:
    for b in sorted(bits, key=len, reverse=True):
        text = re.sub(re.escape(b), HIDDEN, text, flags=re.IGNORECASE)
    return text


def _trigger_draft_json(d) -> dict[str, Any]:
    bits = _private_bits(d)
    condition = {k: (HIDDEN if v and k in ("sender", "subject") and bits else v) for k, v in d.condition.items()}
    return {"source": d.source, "description": _hide(d.description, bits), "condition": condition,
            "action": d.action, "target": d.target, "input": _hide(d.input, bits), "output": d.output,
            "every_s": d.every_s, "cooldown_s": d.cooldown_s, "read_by": d.read_by, "private_hidden": bool(bits)}


def _not_saved(e: Exception) -> str:
    text = str(e)
    return text if text.lower().startswith("not saved") else f"Not saved: {text}"


def build_router(ctx: WebContext) -> APIRouter:
    r = APIRouter()
    drafts: dict[str, tuple[float, Any]] = {}            # schedule drafts
    trigger_drafts: dict[str, tuple[float, Any]] = {}    # trigger drafts (never confirmable as a schedule)
    lock = threading.Lock()

    def keep_draft(draft, store: dict[str, tuple[float, Any]] = drafts) -> str:
        now = time.time()
        with lock:
            for k in [k for k, (t, _) in store.items() if now - t > DRAFT_TTL_S]:
                store.pop(k, None)
            while len(store) >= MAX_DRAFTS:
                store.pop(min(store, key=lambda k: store[k][0]))
            did = secrets.token_hex(12)
            store[did] = (now, draft)
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

    # ---- event triggers (the list is GET /api/triggers via adapters.triggers) ----

    def trigger_store(rt):
        from jarvis.proactive.triggers import TriggerStore

        return TriggerStore(rt.store.conn)

    def need_trigger(rt, tid: str):
        if not TRIGGER_ID.match(tid):
            raise HTTPException(400, "invalid trigger id")
        t = trigger_store(rt).get(tid)
        if t is None:
            raise HTTPException(404, "no such trigger")
        return t

    @r.post("/triggers/draft")
    def trigger_draft(body: TriggerDraftBody) -> dict[str, Any]:
        """Read a sentence into a trigger draft (rules only, no model). Nothing is saved here.
        A question comes back as {"question"}; a refusal (Amazon/Flipkart, a folder outside the
        allowed roots, ...) as a 400 error with the reason."""
        from jarvis.proactive.trigger_parse import TriggerInvalid, TriggerParseError

        text = body.text.strip()
        if not text:
            raise HTTPException(400, "say what to watch and what to do, e.g. 'when a new file arrives in "
                                     "workspace/inbox tell me'")
        p = ctx.proactive()
        defaults: dict[str, Any] = {"output": body.output or p.default_output, "target": body.target.strip()}
        if body.kind:
            defaults["action"] = body.kind
        if body.every_minutes:
            defaults["every_s"] = int(body.every_minutes * 60)
        if body.cooldown_minutes is not None:
            defaults["cooldown_s"] = int(body.cooldown_minutes * 60)
        try:
            draft = p.draft_trigger(text, defaults)
        except TriggerParseError as e:
            return {"draft_id": None, "question": e.question}
        except TriggerInvalid as e:
            ctx.audit.write("trigger_draft_refused", source="dashboard")
            raise HTTPException(400, _not_saved(e))
        did = keep_draft(draft, trigger_drafts)
        ctx.audit.write("trigger_drafted", source="dashboard", source_kind=draft.source, action=draft.action)
        return {"draft_id": did, "draft": _trigger_draft_json(draft),
                "show": _hide(draft.show(), _private_bits(draft))}

    @r.post("/triggers/confirm")
    def trigger_confirm(body: ConfirmBody) -> dict[str, Any]:
        """Save exactly the draft shown under this id (checked again: folders and store lists may change)."""
        from jarvis.proactive.trigger_parse import TriggerInvalid

        with lock:
            item = trigger_drafts.pop(body.draft_id, None)
        if item is None or time.time() - item[0] > DRAFT_TTL_S:
            raise HTTPException(404, "this draft expired or was already answered; read the sentence again")
        p = ctx.proactive()
        try:
            t = p.save_trigger(item[1], "dashboard")   # writes the trigger_added audit event (ids only)
        except TriggerInvalid as e:
            raise HTTPException(400, _not_saved(e))
        return {"saved": {"id": t.id, "name": t.safe_name, "source": t.source, "action": t.action,
                          "enabled": t.enabled},
                "running_here": bool(ctx.extra.get("scheduler_running"))}

    @r.post("/triggers/discard")
    def trigger_discard(body: ConfirmBody) -> dict[str, Any]:
        with lock:
            item = trigger_drafts.pop(body.draft_id, None)
        if item is not None:
            ctx.audit.write("trigger_draft_discarded", source="dashboard")
        return {"discarded": item is not None}

    @r.post("/triggers/{tid}/delete")
    def trigger_delete(tid: str, body: TriggerDeleteBody) -> dict[str, Any]:
        """Same as `jarvis trigger delete`. The confirm step sends the trigger id back."""
        with ctx.runtime() as rt:
            need_trigger(rt, tid)
            if body.confirm != tid:
                raise HTTPException(409, f"to delete {tid}, confirm with its id")
            trigger_store(rt).delete(tid)
            rt.audit.write("trigger_delete", trigger_id=tid, source="dashboard")
        return {"id": tid, "deleted": True}

    @r.post("/triggers/{tid}/{action}")
    def trigger_action(tid: str, action: Literal["pause", "resume"]) -> dict[str, Any]:
        """Same as `jarvis trigger pause|resume`. Resuming checks again at the next poll."""
        p = ctx.proactive()
        with ctx.runtime() as rt:
            need_trigger(rt, tid)
            t = trigger_store(rt).set_enabled(tid, action == "resume", p.now())
            rt.audit.write(f"trigger_{action}", trigger_id=tid, source="dashboard")
        return {"id": tid, "done": action, "enabled": t.enabled}

    @r.get("/triggers/{tid}/runs")
    def trigger_runs(tid: str) -> dict[str, Any]:
        with ctx.runtime() as rt:
            t = need_trigger(rt, tid)
            fires = trigger_store(rt).fires(tid, 20)
        if t.source == "email_from":
            # Like the list (dashboard_triggers): an email rule's events name the sender, P2 until decision #19.
            for f in fires:
                f["detail"] = None
        return {"id": tid, "safe_name": t.safe_name, "runs": fires}

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
