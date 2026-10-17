"""Dharma routing in the dashboard API: POST /api/workspaces/route shows where a goal would go;
POST /api/tasks without a workspace routes, says so, and answers 409 needs_choice when unsure so the
UI can ask; a workspace given by the user is never re-routed. All local; no model."""

from __future__ import annotations

import json

import pytest

pytest.importorskip("fastapi")

from tests.test_web_api_app import H, _client, cfgdir  # noqa: E402, F401


@pytest.fixture
def client(isolated, cfgdir):
    with _client(cfgdir) as c:
        yield c


def _offices(client):
    client.post("/api/workspaces", json={"name": "Digital Marketing"}, headers=H)
    client.put("/api/workspaces/digital-marketing", json={"duties": ["ads", "posts"]}, headers=H)
    client.post("/api/workspaces", json={"name": "Spardha Realty", "slug": "spardha"}, headers=H)
    client.put("/api/workspaces/spardha", json={"duties": ["listings", "site visits"]}, headers=H)


def _routed(isolated):
    return [json.loads(l) for l in (isolated / "data" / "audit.jsonl").read_text(encoding="utf-8").splitlines()
            if '"task_routed"' in l]


def test_route_endpoint_shows_the_decision(client):
    _offices(client)
    r = client.post("/api/workspaces/route", json={"goal": "plan next week's ads"}, headers=H)
    assert r.status_code == 200
    body = r.json()
    assert body["slug"] == "digital-marketing" and body["sure"] and body["line"] == "Routed to Digital Marketing (duties: ads)"
    assert body["candidates"][0] == {"slug": "digital-marketing", "name": "Digital Marketing", "score": 3,
                                     "matched": ["duties: ads"]}
    r = client.post("/api/workspaces/route", json={"goal": "posts about the listings"}, headers=H)
    assert r.json()["slug"] is None and not r.json()["sure"]
    assert [c["slug"] for c in r.json()["candidates"]] == ["digital-marketing", "spardha", "personal"]
    assert client.post("/api/workspaces/route", json={"goal": ""}, headers=H).status_code == 422
    assert client.post("/api/workspaces/route", json={"goal": "x"}).status_code == 401


def test_task_create_routes_and_asks_with_409(client, isolated):
    _offices(client)
    r = client.post("/api/tasks", json={"goal": "plan next week's ads"}, headers=H)
    assert r.status_code == 200 and r.json()["workspace"] == "digital-marketing"
    assert r.json()["routed"] == "Routed to Digital Marketing (duties: ads)"
    assert _routed(isolated)[-1]["source"] == "auto" and _routed(isolated)[-1]["task_id"] == r.json()["id"]

    r = client.post("/api/tasks", json={"goal": "posts about the listings"}, headers=H)
    assert r.status_code == 409
    body = r.json()
    assert [c["slug"] for c in body["needs_choice"]] == ["digital-marketing", "spardha", "personal"]
    assert body["line"].startswith("Which office is this for?") and body["reasons"]
    assert _routed(isolated)[-1]["source"] == "asked"
    tasks = client.get("/api/tasks", headers=H).json()["items"]
    assert len(tasks) == 1  # nothing was created while the question is open

    # the UI asks, the user picks, the second post names the office: never re-routed
    r = client.post("/api/tasks", json={"goal": "posts about the listings", "workspace": "spardha"}, headers=H)
    assert r.status_code == 200 and r.json()["workspace"] == "spardha" and "routed" not in r.json()
    assert len(_routed(isolated)) == 2


def test_task_create_with_a_project_takes_the_owner(client, isolated):
    _offices(client)
    client.put("/api/workspaces/spardha", json={"projects": ["site-video"]}, headers=H)
    r = client.post("/api/tasks", json={"goal": "plan next week's ads", "project": "site-video"}, headers=H)
    assert r.status_code == 200 and r.json()["workspace"] == "spardha" and "routed" not in r.json()
    assert _routed(isolated) == []


def test_only_personal_never_asks(client):
    r = client.post("/api/tasks", json={"goal": "posts about the listings"}, headers=H)
    assert r.status_code == 200 and r.json()["workspace"] == "personal"
