"""Workspaces in the dashboard API: list/create/edit/archive, teams from templates, live stats,
token and origin checks. All local; no model."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from tests.test_web_api_app import H, _client, audit_text, cfgdir  # noqa: E402, F401


@pytest.fixture
def client(isolated, cfgdir):
    with _client(cfgdir) as c:
        yield c


def test_workspace_lifecycle(client, isolated):
    assert [w["slug"] for w in client.get("/api/workspaces", headers=H).json()["items"]] == ["personal"]

    r = client.post("/api/workspaces", json={"name": "Digital Marketing", "brief": "demo"}, headers=H)
    assert r.status_code == 200 and r.json()["slug"] == "digital-marketing"
    assert (isolated / "data" / "workspaces" / "digital-marketing" / "workspace.yaml").exists()

    r = client.put("/api/workspaces/digital-marketing", json={"duties": ["ads", "posts"], "share_personal": False}, headers=H)
    assert r.json()["duties"] == ["ads", "posts"] and r.json()["share_personal"] is False

    r = client.post("/api/workspaces/digital-marketing/teams", json={"template": "research"}, headers=H)
    assert r.status_code == 200 and r.json()["slug"] == "research" and r.json()["members"]
    assert client.post("/api/workspaces/digital-marketing/teams", json={"template": "research"}, headers=H).status_code == 400
    assert client.post("/api/workspaces/digital-marketing/teams", json={"template": "nope"}, headers=H).status_code == 404

    r = client.get("/api/workspaces/digital-marketing", headers=H)
    assert [t["slug"] for t in r.json()["teams"]] == ["research"]
    stats = client.get("/api/workspaces/digital-marketing/stats", headers=H).json()
    assert stats["memories"] == 0 and stats["today"]["model_calls"] == 0

    assert client.post("/api/workspaces/digital-marketing/teams/research/archive", headers=H).json()["archived"] is True
    assert client.get("/api/workspaces/digital-marketing/teams", headers=H).json()["items"] == []
    assert client.get("/api/workspaces/digital-marketing/teams?archived=true", headers=H).json()["items"][0]["slug"] == "research"

    assert client.post("/api/workspaces/digital-marketing/archive", headers=H).json()["archived"] is True
    assert [w["slug"] for w in client.get("/api/workspaces", headers=H).json()["items"]] == ["personal"]
    assert len(client.get("/api/workspaces?archived=true", headers=H).json()["items"]) == 2
    assert client.post("/api/workspaces/digital-marketing/unarchive", headers=H).json()["archived"] is False

    text = audit_text(isolated)
    for ev in ("workspace_created", "workspace_edited", "team_added", "team_archived", "workspace_archived", "workspace_unarchived"):
        assert ev in text, ev


def test_workspace_refusals(client):
    assert client.post("/api/workspaces/personal/archive", headers=H).status_code == 400
    assert client.get("/api/workspaces/nope", headers=H).status_code == 404
    assert client.post("/api/workspaces", json={"name": "x"}, headers=H).status_code == 422   # too short
    assert client.post("/api/workspaces", json={"name": "Dup Co"}, headers=H).status_code == 200
    assert client.post("/api/workspaces", json={"name": "Dup Co"}, headers=H).status_code == 400


def test_workspace_routes_need_token_and_local_origin(client):
    assert client.get("/api/workspaces").status_code == 401
    r = client.post("/api/workspaces", json={"name": "Evil Co"}, headers={**H, "Origin": "https://evil.example"})
    assert r.status_code == 403


def test_chat_session_can_enter_a_workspace(client):
    client.post("/api/workspaces", json={"name": "Acme Ltd"}, headers=H)
    r = client.post("/api/chat/sessions", json={"workspace": "acme-ltd"}, headers=H)
    assert r.status_code == 200 and r.json()["workspace"] == "acme-ltd"
    cid = r.json()["id"]
    r = client.post(f"/api/chat/sessions/{cid}/workspace", json={"workspace": None}, headers=H)
    assert r.json()["workspace"] == "personal"
    assert client.post("/api/chat/sessions", json={"workspace": "nope"}, headers=H).status_code == 400
