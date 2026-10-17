"""The Office page API: offices as rooms with their teams, counts from the task table, the Brain,
the team panel, 404s and the token check. All local; no model."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from fastapi import APIRouter, Depends, HTTPException, Request  # noqa: E402

from tests.test_web_api_app import H, TOKEN, _client, cfgdir  # noqa: E402, F401

PLAN = {"team": "research", "team_label": "research (Acme Ltd)"}


def _mount_office(app) -> None:
    """Until app.py lists routes_office in its module tuple, the test wires the router the same way."""
    if any(getattr(r, "path", "") == "/api/office" for r in app.routes):
        return
    from jarvis.web.routes_office import build_router

    async def require_token(request: Request) -> None:
        if request.headers.get("X-Jarvis-Token") != TOKEN:
            raise HTTPException(401, "missing or wrong token")

    api = APIRouter(prefix="/api", dependencies=[Depends(require_token)])
    api.include_router(build_router(app.state.ctx))
    app.include_router(api)


@pytest.fixture
def client(isolated, cfgdir):
    with _client(cfgdir) as c:
        _mount_office(c.app)
        yield c


def _tasks(isolated):
    from jarvis.core.runtime import open_runtime, task_store

    rt = open_runtime()
    return rt, task_store(rt)


def test_empty_home_has_one_personal_office_and_the_brain(client):
    d = client.get("/api/office", headers=H).json()
    assert [o["slug"] for o in d["offices"]] == ["personal"]
    o = d["offices"][0]
    assert o["teams"] == [] and o["tasks_total"] == {} and o["memories"] == 0 and o["needs_regrant"] == []
    assert o["today"]["line"].startswith("today:")
    assert d["agents"] == {"total": 0, "running": 0}
    assert d["waiting"]["approvals"] == 0 and d["waiting"]["tasks_waiting_approval"] == 0
    assert d["brain"]["memories"] == 0 and isinstance(d["brain"]["skills"], list)
    assert "core_memory" in d["brain"] and "documents" in d["brain"]
    assert d["ts"]


def test_office_counts_come_from_the_task_table(client, isolated):
    client.post("/api/workspaces", json={"name": "Acme Ltd"}, headers=H)
    client.post("/api/workspaces/acme-ltd/teams", json={"template": "research"}, headers=H)
    rt, ts = _tasks(isolated)
    try:
        done = ts.create("compare laptops", workspace="acme-ltd", state="COMPLETED")
        ts.update(done.id, plan=PLAN)
        run = ts.create("compare phones", workspace="acme-ltd", state="RUNNING")
        ts.update(run.id, plan=PLAN, current_step="Web researcher: searching")
        paused = ts.create("compare tablets", workspace="acme-ltd", state="PAUSED")
        ts.update(paused.id, plan=PLAN)
        ts.create("no team here", workspace="acme-ltd", state="BACKLOG")   # counts under the office only
        ts.create("personal errand", workspace="personal", state="RUNNING")
    finally:
        rt.close()

    d = client.get("/api/office", headers=H).json()
    acme = next(o for o in d["offices"] if o["slug"] == "acme-ltd")
    assert acme["tasks_total"] == {"COMPLETED": 1, "RUNNING": 1, "PAUSED": 1, "BACKLOG": 1}
    room = acme["teams"][0]
    assert room["slug"] == "research" and room["colour"] == "teal" and len(room["members"]) == 4
    assert room["tasks"] == {"done": 1, "running": 1, "waiting": 1, "failed": 0}
    assert room["running_now"] == [{"task_id": run.id, "title": "compare phones",
                                    "current_step": "Web researcher: searching", "member": "Web researcher"}]
    assert room["last_run"] and room["last_run"] >= done.updated_at
    assert d["agents"] == {"total": 4, "running": 2}
    assert d["waiting"]["tasks_waiting_approval"] == 1

    p = client.get("/api/office/acme-ltd/teams/research", headers=H).json()
    assert p["office"]["name"] == "Acme Ltd" and p["team"]["slug"] == "research"
    assert p["overview"]["total"] == 3 and p["overview"]["running"] == 1 and p["overview"]["members"] == 4
    assert [t["id"] for t in p["recent_tasks"]] and all(t["team_label"] == PLAN["team_label"] for t in p["recent_tasks"])
    by_name = {a["name"]: a for a in p["agents"]}
    assert by_name["Web researcher"]["status"] == "running" and by_name["Web researcher"]["task_id"] == run.id
    assert by_name["Checker"]["status"] == "idle"
    assert {t["name"] for t in p["tools"]} == {"doc_search", "memory_search", "web_search", "web_fetch"}
    assert all(t["registered"] is True for t in p["tools"])
    assert p["skills"] == []


def test_office_panel_unknown_and_token(client):
    assert client.get("/api/office/nope/teams/research", headers=H).status_code == 404
    assert client.get("/api/office/personal/teams/nope", headers=H).status_code == 404
    assert client.get("/api/office").status_code == 401
    assert client.get("/api/office/personal/teams/research").status_code == 401
