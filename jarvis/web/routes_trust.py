"""Dashboard routes for trust: memory sources, trash and restore, "Why did Jarvis say that?",
and standing approvals (created, listed and revoked only here or in `jarvis approvals`).
"""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from jarvis.web import trust
from jarvis.web.context import WebContext
from jarvis.web.data import memory_json

MEMORY_ID = re.compile(r"^m-\d{4,}$")
GRANT_ID = re.compile(r"^g-[0-9a-f]{8}$")


class TrashBody(BaseModel):
    confirm: bool = False


class GrantBody(BaseModel):
    tool: str = Field(min_length=1, max_length=80)
    constraints: dict[str, dict[str, Any]]
    days: float = Field(default=7, gt=0, le=90)
    max_uses: int = Field(default=10, ge=1, le=1000)
    note: str = Field(default="", max_length=200)


def build_router(ctx: WebContext) -> APIRouter:
    r = APIRouter()

    def _mem(rt, memory_id: str):
        if not MEMORY_ID.match(memory_id):
            raise HTTPException(400, "invalid memory id")
        m = rt.memory.get(memory_id)
        if not m:
            raise HTTPException(404, "no such memory")
        return m

    # ---- memory: source, trash, restore ----

    @r.get("/memory/{memory_id}/source")
    def memory_source(memory_id: str, reveal: bool = False) -> dict[str, Any]:
        with ctx.runtime() as rt:
            m = _mem(rt, memory_id)
            if reveal and m.sensitivity in ("sensitive", "secret"):
                rt.audit.write("memory_revealed", source="dashboard", id=memory_id, sensitivity=m.sensitivity,
                               part="source")
            return trust.memory_source(rt, m, reveal)

    @r.post("/memory/{memory_id}/activate")
    def memory_activate(memory_id: str) -> dict[str, Any]:
        with ctx.runtime() as rt:
            m = _mem(rt, memory_id)
            if m.status != "archived":
                raise HTTPException(409, f"memory is {m.status}; only archived memories can be made active")
            m.status = "active"
            rt.memory.update(m)
            rt.audit.write("memory_activated", source="dashboard", id=memory_id)
            return memory_json(m)

    @r.post("/memory/{memory_id}/trash")
    def memory_trash(memory_id: str, body: TrashBody) -> dict[str, Any]:
        if not body.confirm:
            raise HTTPException(400, "confirm the delete first (it moves the memory to memory/.trash)")
        with ctx.runtime() as rt:
            _mem(rt, memory_id)
            dest = rt.memory.trash(memory_id)
            rt.audit.write("memory_trashed", source="dashboard", id=memory_id, file=dest.name)
            return {"trashed": {"file": dest.name, "id": memory_id}}

    @r.get("/memory-trash")
    def memory_trash_list() -> dict[str, Any]:
        with ctx.runtime() as rt:
            return {"items": trust.trash_json(rt)}

    @r.post("/memory-trash/{file}/restore")
    def memory_restore(file: str) -> dict[str, Any]:
        with ctx.runtime() as rt:
            try:
                m = rt.memory.restore(file)
            except KeyError:
                raise HTTPException(404, "no such file in the memory trash")
            except ValueError as e:
                raise HTTPException(409, str(e))
            rt.audit.write("memory_restored", source="dashboard", id=m.id, file=file)
            return memory_json(m)

    # ---- past chat lines and "why did Jarvis say that?" ----

    @r.get("/sessions/{session_id}/messages")
    def session_messages(session_id: str, around: int | None = None, n: int = 6) -> dict[str, Any]:
        if not re.match(r"^[\w.:-]{1,80}$", session_id):
            raise HTTPException(400, "invalid session id")
        with ctx.runtime() as rt:
            return {"session_id": session_id, "items": trust.session_lines(rt, session_id, around, n)}

    @r.get("/sessions/{session_id}/turns")
    def session_turns(session_id: str, limit: int = 20) -> dict[str, Any]:
        """Recorded turns of any chat (web, terminal or Telegram), newest first, for the "why" panel."""
        if not re.match(r"^[\w.:-]{1,80}$", session_id):
            raise HTTPException(400, "invalid session id")
        with ctx.runtime() as rt:
            trust.ensure_turn_table(rt.store.conn)
            rows = rt.store.conn.execute(
                "SELECT id, ts, reply_message_id FROM turn_context WHERE session_id=? ORDER BY id DESC LIMIT ?",
                (session_id, max(1, min(int(limit), 100)))).fetchall()
        return {"session_id": session_id,
                "items": [{"turn_id": r[0], "ts": r[1], "reply_message_id": r[2]} for r in rows]}

    @r.get("/chat/turns/{turn_id}")
    def chat_turn(turn_id: int) -> dict[str, Any]:
        with ctx.runtime() as rt:
            view = trust.turn_view(rt, turn_id)
        if view is None:
            raise HTTPException(404, "no record for this reply")
        return view

    # ---- standing approvals ----

    @r.get("/grants")
    def grants() -> dict[str, Any]:
        from jarvis.control.grants import KINDS

        with ctx.runtime() as rt:
            store = trust.grant_store(rt)
            now = store.clock()
            return {"items": [g.public(now) for g in store.list()], "tools": trust.grant_tools(rt),
                    "kinds": list(KINDS)}

    @r.post("/grants")
    def grant_create(body: GrantBody) -> dict[str, Any]:
        from jarvis.control.grants import GrantError

        with ctx.runtime() as rt:
            tools = {t["name"]: t["tier"] for t in trust.grant_tools(rt)}
            if body.tool not in tools:
                raise HTTPException(400, f"{body.tool} cannot have a standing approval (only enabled T1/T2 tools)")
            store = trust.grant_store(rt)
            try:
                g = store.create(body.tool, tools[body.tool], body.constraints, body.days, body.max_uses, body.note,
                                 created_by="dashboard")
            except GrantError as e:
                rt.audit.write("grant_refused", source="dashboard", tool=body.tool, detail=str(e))
                raise HTTPException(400, str(e))
            rt.audit.write("grant_created", source="dashboard", grant_id=g.id, tool=g.tool, tier=g.tier,
                           constraints=g.constraints, expires=g.expires, max_uses=g.max_uses)
            return g.public(store.clock())

    @r.post("/grants/{grant_id}/revoke")
    def grant_revoke(grant_id: str) -> dict[str, Any]:
        if not GRANT_ID.match(grant_id):
            raise HTTPException(400, "invalid grant id")
        with ctx.runtime() as rt:
            store = trust.grant_store(rt)
            try:
                g = store.revoke(grant_id)
            except KeyError:
                raise HTTPException(404, "no such grant")
            rt.audit.write("grant_revoked", source="dashboard", grant_id=grant_id)
            return g.public(store.clock())

    @r.get("/grants/{grant_id}/uses")
    def grant_uses(grant_id: str) -> dict[str, Any]:
        if not GRANT_ID.match(grant_id):
            raise HTTPException(400, "invalid grant id")
        with ctx.runtime() as rt:
            store = trust.grant_store(rt)
            if not store.get(grant_id):
                raise HTTPException(404, "no such grant")
            return {"items": store.uses(grant_id)}

    return r
