"""Narada in the dashboard API: an office files a request to another, lists them, archives them.
Refusals are 400, unknown offices 404; every change is audited with source dashboard. No model."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from tests.test_web_api_app import H, _client, audit_text, cfgdir  # noqa: E402, F401


@pytest.fixture
def client(isolated, cfgdir):
    with _client(cfgdir) as c:
        yield c


def test_request_lifecycle(client, isolated):
    client.post("/api/workspaces", json={"name": "Acme Ltd"}, headers=H)
    client.post("/api/workspaces", json={"name": "Globex"}, headers=H)

    r = client.post("/api/workspaces/acme-ltd/requests", json={"to": "globex", "goal": "draft the brief"}, headers=H)
    assert r.status_code == 400 and "add it to allies" in r.json()["detail"]
    r = client.post("/api/workspaces/personal/requests", json={"to": "globex", "goal": "draft the brief"}, headers=H)
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "lr-001" and body["from"] == "personal" and body["to"] == "globex"
    assert body["state"] == "requested" and body["task_id"] == "t-001" and body["archived"] is False

    items = client.get("/api/workspaces/globex/requests", headers=H).json()["items"]
    assert [x["id"] for x in items] == ["lr-001"]
    assert client.get("/api/workspaces/acme-ltd/requests", headers=H).json()["items"] == []
    assert client.get("/api/workspaces/personal/requests", headers=H).json()["items"][0]["task_id"] == "t-001"

    assert client.post("/api/workspaces/requests/lr-001/archive", headers=H).json()["archived"] is True
    assert client.get("/api/workspaces/globex/requests", headers=H).json()["items"] == []
    assert client.get("/api/workspaces/globex/requests?archived=true", headers=H).json()["items"][0]["id"] == "lr-001"
    assert client.post("/api/workspaces/requests/lr-001/unarchive", headers=H).json()["archived"] is False

    text = audit_text(isolated)
    for ev in ("loka_request_made", "loka_request_archived", "loka_request_unarchived"):
        assert ev in text, ev
    assert text.count('"source": "dashboard"') >= 3


def test_request_refusals(client):
    client.post("/api/workspaces", json={"name": "Acme Ltd"}, headers=H)
    assert client.post("/api/workspaces/nope/requests", json={"to": "acme-ltd", "goal": "x"}, headers=H).status_code == 404
    assert client.post("/api/workspaces/personal/requests", json={"to": "nope", "goal": "x"}, headers=H).status_code == 404
    assert client.post("/api/workspaces/personal/requests", json={"to": "personal", "goal": "x"}, headers=H).status_code == 400
    assert client.post("/api/workspaces/personal/requests", json={"to": "acme-ltd", "goal": ""}, headers=H).status_code == 422
    assert client.get("/api/workspaces/nope/requests", headers=H).status_code == 404
    assert client.post("/api/workspaces/requests/lr-999/archive", headers=H).status_code == 404
    client.post("/api/workspaces/acme-ltd/archive", headers=H)
    r = client.post("/api/workspaces/personal/requests", json={"to": "acme-ltd", "goal": "x"}, headers=H)
    assert r.status_code == 400 and "archived" in r.json()["detail"]


def test_request_routes_need_token_and_local_origin(client):
    assert client.get("/api/workspaces/personal/requests").status_code == 401
    r = client.post("/api/workspaces/personal/requests", json={"to": "x", "goal": "y"},
                    headers={**H, "Origin": "https://evil.example"})
    assert r.status_code == 403
