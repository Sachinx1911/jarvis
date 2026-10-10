"""FastAPI app for the dashboard (PLAN.md section 18, Phase 7).

Security (most important):
- Listens on 127.0.0.1 only (the CLI refuses other hosts). Requests from non-loopback
  clients, unknown Host headers (DNS rebinding) and foreign Origins are refused.
- Every /api call needs the random access token (header X-Jarvis-Token or Authorization:
  Bearer). There is no cookie auth, so a forged cross-site request has nothing to ride on (CSRF).
- CORS: no wildcard; only the dashboard's own origin plus dev origins listed in config/web.yaml.
- No endpoint returns a secret. Sensitive memories are masked unless revealed (audited).
- Approvals need a click that echoes the hash of the exact arguments shown.
- The emergency stop endpoint is async and touches only a file, so it answers even while a
  model call or tool is stuck in a worker thread.
"""

from __future__ import annotations

import hmac
import time
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import Any, Iterator, Literal

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from jarvis.control.audit import AuditLog
from jarvis.control.stop import EmergencyStop, StopSwitch
from jarvis.core.runtime import Runtime, open_runtime, task_store
from jarvis.memory.store import MemoryRejected
from jarvis.paths import default_paths
from jarvis.providers.base import ProviderError
from jarvis.routing.policy import RoutingError
from jarvis.secrets import get_secret
from jarvis.tasks.store import FINAL, PRIORITIES, TransitionError
from jarvis.web import adapters, data
from jarvis.web.approvals import ApprovalBroker, ApprovalError
from jarvis.web.settings import STATIC_DIR, WebSettings, is_loopback
from jarvis.web.workers import ChatFactory, ChatManager, TaskManager, default_chat_factory

MAX_PARALLEL_TASKS = 2  # PLAN.md 10.1: at most 2 big tasks at once (16 GB RAM)

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    # Next.js static export inlines small bootstrap scripts, hence 'unsafe-inline' for scripts.
    # Everything is same-origin; no external fonts, scripts or connections.
    "Content-Security-Policy": ("default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' "
                                "'unsafe-inline'; img-src 'self' data:; connect-src 'self'; font-src 'self'; "
                                "object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"),
}


# ---- request bodies ----

class ChatSend(BaseModel):
    text: str = Field(min_length=1, max_length=20000)


class MemoryEdit(BaseModel):
    name: str | None = None
    type: Literal["fact", "preference", "procedure", "constraint", "episode"] | None = None
    body: str | None = None
    subject: str | None = None
    description: str | None = None
    when_to_use: str | None = None
    summary_en: str | None = None
    keywords: str | None = None
    sensitivity: Literal["public", "normal", "sensitive"] | None = None
    scope: str | None = None
    expires: str | None = None


class TaskCreate(BaseModel):
    goal: str = Field(min_length=1, max_length=4000)
    project: str | None = Field(default=None, max_length=80)
    priority: Literal["high", "normal", "low"] = "normal"
    deadline: str | None = Field(default=None, max_length=40)
    run: bool = False


class ApprovalAnswer(BaseModel):
    decision: Literal["approve", "deny"]
    args_sha256: str = ""


class ToolEdit(BaseModel):
    tier: Literal["T0", "T1", "T2", "T3", "T4"] | None = None
    enabled: bool | None = None


class StopBody(BaseModel):
    engaged: bool
    reason: str = Field(default="", max_length=200)


# ---- app ----

def create_app(settings: WebSettings | None = None, token: str | None = None, *,
               chat_factory: ChatFactory | None = None, task_runner_factory=None,
               allowed_hosts: list[str] | None = None, trusted_clients: set[str] | None = None,
               static_dir: Path | None = STATIC_DIR) -> FastAPI:
    settings = settings or WebSettings()
    if not token:
        raise ValueError("the dashboard needs an access token")
    paths = default_paths()
    paths.ensure()
    audit = AuditLog(paths.audit_log)
    stop = StopSwitch(paths.data)
    broker = ApprovalBroker(audit, settings.approval_timeout_s)
    chats = ChatManager(broker, chat_factory or default_chat_factory(settings.provider), settings.chat_idle_minutes)
    tasks = TaskManager(broker, audit, settings.provider, task_runner_factory)
    origins = set(settings.origins())
    hosts = set(allowed_hosts if allowed_hosts is not None else settings.hosts())
    clients = trusted_clients or set()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        broker.deny_all("shutdown")  # nobody can answer any more
        chats.close_all()            # end chats like /exit, so memories are saved

    app = FastAPI(title="Jarvis dashboard", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.broker, app.state.chats, app.state.tasks, app.state.stop = broker, chats, tasks, stop

    @app.middleware("http")
    async def guard(request: Request, call_next):
        client = request.client.host if request.client else ""
        if client not in clients and not is_loopback(client):
            return JSONResponse({"detail": "local access only"}, status_code=403)
        if request.headers.get("host", "") not in hosts:
            return JSONResponse({"detail": "unknown host"}, status_code=400)
        origin = request.headers.get("origin")
        if origin is not None and origin.rstrip("/") not in origins:
            return JSONResponse({"detail": "origin not allowed"}, status_code=403)
        if request.headers.get("sec-fetch-site") == "cross-site":
            return JSONResponse({"detail": "cross-site request refused"}, status_code=403)
        response = await call_next(request)
        for k, v in SECURITY_HEADERS.items():
            response.headers.setdefault(k, v)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    extra = [o for o in settings.origins() if o not in settings.origins()[:3]]
    if extra:  # dev origins only (e.g. `npm run dev`); the built dashboard is same-origin
        app.add_middleware(CORSMiddleware, allow_origins=extra, allow_credentials=False,
                           allow_methods=["GET", "POST", "PATCH"],
                           allow_headers=["X-Jarvis-Token", "Authorization", "Content-Type"])

    async def require_token(request: Request) -> None:
        supplied = request.headers.get("x-jarvis-token", "")
        auth = request.headers.get("authorization", "")
        if not supplied and auth.lower().startswith("bearer "):
            supplied = auth[7:].strip()
        if not supplied or not hmac.compare_digest(supplied.encode(), token.encode()):
            raise HTTPException(401, "missing or wrong dashboard token")

    api = APIRouter(prefix="/api", dependencies=[Depends(require_token)])

    @contextmanager
    def runtime() -> Iterator[Runtime]:
        rt = open_runtime()
        try:
            yield rt
        finally:
            rt.close()

    # ---- health and emergency stop (async: never waits on worker threads) ----

    @api.get("/health")
    async def health() -> dict[str, Any]:
        return {"ok": True, "stop_engaged": stop.engaged(), "pending_approvals": len(broker.pending()),
                "running_tasks": tasks.running(), "chats": len(chats.list())}

    @api.get("/stop")
    async def stop_status() -> dict[str, Any]:
        detail = stop.path.read_text(encoding="utf-8").strip() if stop.engaged() else ""
        return {"engaged": stop.engaged(), "detail": detail}

    @api.post("/stop")
    async def set_stop(body: StopBody) -> dict[str, Any]:
        if body.engaged:
            stop.engage(f"dashboard: {body.reason}".strip())
            denied = broker.deny_all("stopped")
            audit.write("emergency_stop", source="dashboard", reason=body.reason, approvals_denied=denied)
        else:
            stop.release()
            audit.write("emergency_stop_released", source="dashboard")
        return {"engaged": stop.engaged()}

    # ---- chat ----

    @api.post("/chat/sessions")
    def chat_new() -> dict[str, Any]:
        try:
            return chats.create()
        except RoutingError as e:
            raise HTTPException(400, f"routing error: {e}")

    @api.get("/chat/sessions")
    def chat_list() -> list[dict]:
        return chats.list()

    @api.post("/chat/sessions/{cid}/messages")
    def chat_send(cid: str, body: ChatSend) -> dict[str, Any]:
        try:
            return chats.send(cid, body.text)
        except KeyError:
            raise HTTPException(404, "chat session not found (it may have expired); start a new one")
        except EmergencyStop as e:
            raise HTTPException(409, f"stopped: {e}")
        except ProviderError as e:
            raise HTTPException(502, f"model error ({e.kind}): {e}")
        except (MemoryRejected, ValueError) as e:
            raise HTTPException(400, f"not saved: {e}")

    @api.post("/chat/sessions/{cid}/end")
    def chat_end(cid: str) -> dict[str, Any]:
        try:
            results = chats.end(cid)
        except KeyError:
            raise HTTPException(404, "chat session not found")
        except (ProviderError, EmergencyStop) as e:
            return {"ended": True, "learned": [], "error": str(e)}
        return {"ended": True, "learned": [{"action": a, "id": m} for a, m in results]}

    # ---- memory ----

    @api.get("/memory")
    def memory_list(q: str = "", type: str | None = None, all: bool = False) -> dict[str, Any]:
        with runtime() as rt:
            if q.strip():
                hits = rt.memory.search(q, k=20)
                return {"items": [{**data.memory_json(h.memory), "score": round(h.score, 4)} for h in hits]}
            mems = rt.memory.list(type=type or None, status=None if all else "active")
            return {"items": [data.memory_json(m) for m in mems]}

    @api.get("/memory/{memory_id}")
    def memory_show(memory_id: str) -> dict[str, Any]:
        with runtime() as rt:
            m = rt.memory.get(memory_id)
            if not m:
                raise HTTPException(404, "no such memory")
            return data.memory_json(m)

    @api.post("/memory/{memory_id}/reveal")
    def memory_reveal(memory_id: str) -> dict[str, Any]:
        with runtime() as rt:
            m = rt.memory.get(memory_id)
            if not m:
                raise HTTPException(404, "no such memory")
            rt.audit.write("memory_revealed", source="dashboard", id=memory_id, sensitivity=m.sensitivity)
            return data.memory_json(m, reveal=True)

    @api.patch("/memory/{memory_id}")
    def memory_edit(memory_id: str, body: MemoryEdit) -> dict[str, Any]:
        changes = body.model_dump(exclude_unset=True)
        with runtime() as rt:
            try:
                m = data.edit_memory(rt, memory_id, changes)
            except KeyError:
                raise HTTPException(404, "no such memory")
            except (MemoryRejected, ValueError) as e:
                raise HTTPException(400, str(e))
            rt.audit.write("memory_edited", source="dashboard", id=memory_id, fields=sorted(changes))
            return data.memory_json(m, reveal=True)

    @api.post("/memory/{memory_id}/archive")
    def memory_archive(memory_id: str) -> dict[str, Any]:
        with runtime() as rt:
            try:
                m = rt.memory.archive(memory_id)
            except KeyError:
                raise HTTPException(404, "no such memory")
            rt.audit.write("memory_archived", source="dashboard", id=memory_id)
            return data.memory_json(m)

    # ---- tasks ----

    @api.get("/tasks")
    def task_list(all: bool = True) -> dict[str, Any]:
        running = set(tasks.running())
        with runtime() as rt:
            items = [data.task_json(rt, t, t.id in running, tasks.progress.get(t.id))
                     for t in task_store(rt).list(include_final=all)]
        return {"items": items, "running": sorted(running)}

    @api.post("/tasks")
    def task_create(body: TaskCreate) -> dict[str, Any]:
        from jarvis.cli_tasks import create_task

        with runtime() as rt:
            tid = create_task(rt, body.goal, body.project or None, PRIORITIES[body.priority], body.deadline or None)
            rt.audit.write("task_created", source="dashboard", task_id=tid)
        started = _start(tid) if body.run else False
        return {"id": tid, "started": started}

    @api.get("/tasks/{task_id}")
    def task_show(task_id: str) -> dict[str, Any]:
        with runtime() as rt:
            t = task_store(rt).get(task_id)
            if not t:
                raise HTTPException(404, "no such task")
            d = data.task_json(rt, t, tasks.is_running(task_id), tasks.progress.get(task_id))
            d["events"] = task_store(rt).events(task_id)
            d["receipt"] = data.receipt_text(rt, task_id)
            d["approvals"] = [p for p in broker.pending() if p["task_id"] == task_id]
            return d

    def _start(task_id: str) -> bool:
        if stop.engaged():
            raise HTTPException(409, "emergency stop is on")
        if tasks.is_running(task_id):
            raise HTTPException(409, "task is already running")
        if len(tasks.running()) >= MAX_PARALLEL_TASKS:
            raise HTTPException(409, f"{MAX_PARALLEL_TASKS} tasks are already running")
        with runtime() as rt:
            t = task_store(rt).get(task_id)
            if not t:
                raise HTTPException(404, "no such task")
            if t.state in ("COMPLETED", "CANCELLED"):
                raise HTTPException(409, f"task is {t.state}")
            rt.audit.write("task_run_requested", source="dashboard", task_id=task_id, state=t.state)
        return tasks.start(task_id)

    @api.post("/tasks/{task_id}/run")
    def task_run(task_id: str) -> dict[str, Any]:
        return {"id": task_id, "started": _start(task_id)}

    @api.post("/tasks/{task_id}/resume")
    def task_resume(task_id: str) -> dict[str, Any]:
        return {"id": task_id, "started": _start(task_id)}

    @api.post("/tasks/resume-all")
    def task_resume_all() -> dict[str, Any]:
        started = []
        with runtime() as rt:
            pending = [t.id for t in task_store(rt).resumable()]
        for tid in pending:
            if len(tasks.running()) >= MAX_PARALLEL_TASKS:
                break
            if not tasks.is_running(tid) and tasks.start(tid):
                started.append(tid)
        return {"started": started, "waiting": [t for t in pending if t not in started]}

    @api.post("/tasks/{task_id}/cancel")
    def task_cancel(task_id: str) -> dict[str, Any]:
        with runtime() as rt:
            ts = task_store(rt)
            t = ts.get(task_id)
            if not t:
                raise HTTPException(404, "no such task")
            if t.state in FINAL:
                raise HTTPException(409, f"task is already {t.state}")
            try:
                ts.set_state(task_id, "CANCELLED", "cancelled from the dashboard")
            except TransitionError as e:
                raise HTTPException(409, str(e))
            rt.audit.write("task_cancelled", source="dashboard", task_id=task_id)
        for p in broker.pending():
            if p["task_id"] == task_id:
                broker.resolve(p["id"], False)
        return {"id": task_id, "state": "CANCELLED"}

    # ---- approvals ----

    @api.get("/approvals")
    async def approvals() -> dict[str, Any]:
        return {"pending": broker.pending(), "recent": broker.history()[:20], "timeout_s": broker.timeout_s,
                "now": time.time()}

    @api.post("/approvals/{approval_id}")
    async def approval_answer(approval_id: int, body: ApprovalAnswer) -> dict[str, Any]:
        try:
            return broker.resolve(approval_id, body.decision == "approve", body.args_sha256)
        except KeyError:
            raise HTTPException(404, "no such pending approval (answered or timed out)")
        except ApprovalError as e:
            raise HTTPException(409, str(e))

    # ---- agents ----

    @api.get("/agents")
    def agents(limit: int = 100) -> dict[str, Any]:
        with runtime() as rt:
            return data.agent_runs(rt, max(1, min(limit, 500)))

    # ---- connectors and tools ----

    @api.get("/connectors")
    def connectors() -> dict[str, Any]:
        with runtime() as rt:
            out = data.tools_json(rt)
            out["external"] = adapters.connectors(rt.paths.home)
            out["documents"] = adapters.documents(rt.paths.home)
            out["telegram"] = adapters.telegram(rt.paths.home)
            out["voice"] = adapters.voice(rt.paths.home)
            return out

    @api.patch("/connectors/tools/{name}")
    def tool_edit(name: str, body: ToolEdit) -> dict[str, Any]:
        with runtime() as rt:
            try:
                return data.edit_tool(rt, name, body.tier, body.enabled)
            except KeyError:
                raise HTTPException(404, "no such tool")
            except data.RegistryRefused as e:
                rt.audit.write("registry_edit_refused", source="dashboard", tool=name, detail=str(e))
                raise HTTPException(403, str(e))

    @api.get("/connectors/health")
    def connectors_health() -> dict[str, Any]:
        from jarvis.providers import make_provider
        from jarvis.tools.catalog import file_roots

        with runtime() as rt:
            checks = [{"name": "tavily key", "ok": bool(get_secret("tavily_api_key")),
                       "detail": "set" if get_secret("tavily_api_key") else "not set (jarvis secret set tavily_api_key)"}]
            roots = file_roots(rt.paths.home, rt.config.tools)
            checks.append({"name": "file folders", "ok": all(r.exists() for r in roots),
                           "detail": ", ".join(str(r) for r in roots)})
            for name in rt.config.routing.get("approved_providers") or []:
                try:
                    h = make_provider(name, rt.config).health()
                    checks.append({"name": name, "ok": h.ok, "detail": h.detail})
                except Exception as e:
                    checks.append({"name": name, "ok": False, "detail": f"{type(e).__name__}: {e}"})
            return {"checks": checks}

    # ---- schedules ----

    @api.get("/schedules")
    def schedules() -> dict[str, Any]:
        return adapters.schedules(default_paths().home)

    # ---- settings and usage ----

    @api.get("/settings")
    def settings_view() -> dict[str, Any]:
        with runtime() as rt:
            routing = rt.config.routing
            return {
                "stop": {"engaged": stop.engaged()},
                "cloud": {"cloud_allowed": bool(routing.get("cloud_allowed", False)), "mode": routing.get("mode"),
                          "approved_providers": routing.get("approved_providers") or [],
                          "switch": adapters.cloud(rt.paths.home)},
                "routes": data.routes_json(rt),
                "dashboard": {"host": settings.host, "port": settings.port,
                              "approval_timeout_s": settings.approval_timeout_s,
                              "provider_override": settings.provider},
                "home": str(rt.paths.home),
                "modules": {k: adapters._installed(v[0]) for k, v in adapters.HOOKS.items()},
            }

    @api.get("/usage")
    def usage(days: int = 30) -> dict[str, Any]:
        with runtime() as rt:
            return data.usage_json(rt, days)

    app.include_router(api)

    # ---- the built dashboard (dashboard/out), same origin as the API ----
    if static_dir and (static_dir / "index.html").exists():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="dashboard")
    else:
        @app.get("/", response_class=HTMLResponse)
        def not_built() -> str:
            return ("<!doctype html><meta charset=utf-8><title>Jarvis</title><p>The dashboard is not built yet. "
                    "Run <code>npm install</code> and <code>npm run build</code> in <code>dashboard/</code>.</p>")

    return app
