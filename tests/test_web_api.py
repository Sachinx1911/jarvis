"""Phase 7 dashboard API: token, origin and host checks, approvals, stop, memory masking,
connector registry edits, tasks and usage. Offline: fake provider only."""

import threading
import time

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from jarvis.core.runtime import make_chat, open_runtime  # noqa: E402
from jarvis.memory.model import Memory  # noqa: E402
from jarvis.providers.fake import FakeProvider  # noqa: E402
from jarvis.web.app import create_app  # noqa: E402
from jarvis.web.approvals import args_hash  # noqa: E402
from jarvis.web.settings import WebSettings, get_or_create_token  # noqa: E402

TOKEN = "test-token-not-real"
H = {"X-Jarvis-Token": TOKEN}


class Scripted:
    """Chat factory: a fake provider with a script, shared by every chat in the test."""

    def __init__(self, script=None, provider=None):
        self.provider = provider or FakeProvider(script=script or [])

    def __call__(self, rt, approver):
        session = make_chat(rt, "fake", approver)
        session.provider = session.loop.provider = self.provider
        return session


def _client(factory=None, timeout=5.0, **kw) -> TestClient:
    settings = WebSettings(approval_timeout_s=timeout, provider="fake", **kw)
    app = create_app(settings, TOKEN, chat_factory=factory or Scripted(), allowed_hosts=["testserver"],
                     trusted_clients={"testclient"}, static_dir=None)
    return TestClient(app)


@pytest.fixture
def client(isolated):
    with _client() as c:
        yield c


# ---- authentication, origin, host ----

def test_no_token_is_401(client):
    for method, path in [("get", "/api/health"), ("get", "/api/memory"), ("post", "/api/stop"),
                         ("get", "/api/tasks"), ("get", "/api/approvals"), ("get", "/api/usage")]:
        r = getattr(client, method)(path)
        assert r.status_code == 401, path


def test_wrong_token_is_401(client):
    assert client.get("/api/health", headers={"X-Jarvis-Token": "nope"}).status_code == 401
    assert client.get("/api/health", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_token_in_header_or_bearer(client):
    assert client.get("/api/health", headers=H).json()["ok"] is True
    assert client.get("/api/health", headers={"Authorization": f"Bearer {TOKEN}"}).status_code == 200


def test_wrong_origin_refused_even_with_token(client):
    r = client.post("/api/stop", headers={**H, "Origin": "https://evil.example"}, json={"engaged": True})
    assert r.status_code == 403
    assert client.get("/api/stop", headers=H).json()["engaged"] is False
    r = client.get("/api/health", headers={**H, "Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403


def test_own_origin_allowed(client):
    r = client.get("/api/health", headers={**H, "Origin": "http://127.0.0.1:8765"})
    assert r.status_code == 200
    assert "access-control-allow-origin" not in r.headers  # same-origin only, no CORS wildcard


def test_dev_origin_cors_is_exact(isolated):
    with _client(dev_origins=["http://localhost:3000"]) as c:
        ok = c.options("/api/health", headers={"Origin": "http://localhost:3000",
                                               "Access-Control-Request-Method": "GET",
                                               "Access-Control-Request-Headers": "x-jarvis-token"})
        assert ok.headers.get("access-control-allow-origin") == "http://localhost:3000"
        bad = c.options("/api/health", headers={"Origin": "http://evil.example",
                                                "Access-Control-Request-Method": "GET"})
        assert bad.headers.get("access-control-allow-origin") is None


def test_unknown_host_refused(client):
    assert client.get("/api/health", headers={**H, "Host": "evil.example"}).status_code == 400


def test_security_headers(client):
    r = client.get("/api/health", headers=H)
    assert r.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert r.headers["cache-control"] == "no-store"


def test_token_created_once_and_kept_in_keyring(isolated):
    from jarvis.secrets import get_secret

    t1 = get_or_create_token()
    assert len(t1) >= 40 and get_secret("dashboard_token") == t1
    assert get_or_create_token() == t1
    assert get_or_create_token(rotate=True) != t1


def test_no_secrets_exposed(client):
    from jarvis.secrets import set_secret

    set_secret("tavily_api_key", "tvly-supersecretvalue123")
    for path in ("/api/settings", "/api/connectors", "/api/connectors/health", "/api/health"):
        body = client.get(path, headers=H).text
        assert "tvly-supersecret" not in body and TOKEN not in body, path


# ---- emergency stop ----

def test_stop_endpoint_engages_and_releases(client, isolated):
    r = client.post("/api/stop", headers=H, json={"engaged": True, "reason": "test"})
    assert r.json() == {"engaged": True}
    assert (isolated / "data" / "STOP").exists()
    sid = client.post("/api/chat/sessions", headers=H).json()["id"]
    r = client.post(f"/api/chat/sessions/{sid}/messages", headers=H, json={"text": "hello"})
    assert r.status_code == 409 and "stop" in r.json()["detail"]
    assert client.post("/api/stop", headers=H, json={"engaged": False}).json() == {"engaged": False}
    assert client.post(f"/api/chat/sessions/{sid}/messages", headers=H, json={"text": "hello"}).status_code == 200


def test_stop_answers_while_model_is_stuck(isolated):
    gate = threading.Event()

    class Stuck(FakeProvider):
        def generate(self, req):
            gate.wait(10)
            return super().generate(req)

    with _client(factory=Scripted(provider=Stuck())) as c:
        sid = c.post("/api/chat/sessions", headers=H).json()["id"]
        result = {}
        t = threading.Thread(target=lambda: result.update(
            r=c.post(f"/api/chat/sessions/{sid}/messages", headers=H, json={"text": "hello"})))
        t.start()
        time.sleep(0.3)
        start = time.time()
        r = c.post("/api/stop", headers=H, json={"engaged": True, "reason": "stuck"})
        assert r.status_code == 200 and time.time() - start < 2
        assert (isolated / "data" / "STOP").exists()
        gate.set()
        t.join(10)
        assert result["r"].status_code == 200  # the stuck call finishes; the next one is blocked


def test_stop_denies_pending_approvals(isolated):
    (isolated / "workspace").mkdir(exist_ok=True)
    (isolated / "workspace" / "note.txt").write_text("old", encoding="utf-8")
    script = [{"tool": "overwrite_file", "arguments": {"path": "note.txt", "content": "new"}}, "ok"]
    with _client(factory=Scripted(script)) as c:
        sid = c.post("/api/chat/sessions", headers=H).json()["id"]
        res = {}
        t = threading.Thread(target=lambda: res.update(
            r=c.post(f"/api/chat/sessions/{sid}/messages", headers=H, json={"text": "change it"})))
        t.start()
        _wait_pending(c)
        c.post("/api/stop", headers=H, json={"engaged": True})
        t.join(10)
        assert (isolated / "workspace" / "note.txt").read_text(encoding="utf-8") == "old"
        assert c.get("/api/approvals", headers=H).json()["recent"][0]["outcome"] == "stopped"


# ---- approvals ----

def _wait_pending(c, n=1, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        pending = c.get("/api/approvals", headers=H).json()["pending"]
        if len(pending) >= n:
            return pending
        time.sleep(0.05)
    raise AssertionError("no pending approval appeared")


def _overwrite_chat(isolated, decision, timeout=5.0, wrong_hash=False):
    (isolated / "workspace").mkdir(exist_ok=True)
    (isolated / "workspace" / "note.txt").write_text("old", encoding="utf-8")
    script = [{"tool": "overwrite_file", "arguments": {"path": "note.txt", "content": "new"}}, "Done, sir."]
    with _client(factory=Scripted(script), timeout=timeout) as c:
        sid = c.post("/api/chat/sessions", headers=H).json()["id"]
        res = {}
        t = threading.Thread(target=lambda: res.update(
            r=c.post(f"/api/chat/sessions/{sid}/messages", headers=H, json={"text": "overwrite note"})))
        t.start()
        if decision is None:
            t.join(10)
            return c, res["r"], None
        p = _wait_pending(c)[0]
        assert p["tool"] == "overwrite_file" and p["tier"] == "T2"
        assert p["arguments"] == {"path": "note.txt", "content": "new"}  # exact arguments shown
        assert p["args_sha256"] == args_hash(p["arguments"])
        answer = {"decision": decision, "args_sha256": "0" * 64 if wrong_hash else p["args_sha256"]}
        a = c.post(f"/api/approvals/{p['id']}", headers=H, json=answer)
        if wrong_hash:
            assert a.status_code == 409
            c.post(f"/api/approvals/{p['id']}", headers=H, json={"decision": "deny"})
        t.join(10)
        recent = c.get("/api/approvals", headers=H).json()["recent"]
        return c, res["r"], recent


def test_approval_approve_runs_the_tool(isolated):
    _, r, recent = _overwrite_chat(isolated, "approve")
    assert r.status_code == 200 and r.json()["reply"] == "Done, sir."
    assert (isolated / "workspace" / "note.txt").read_text(encoding="utf-8") == "new"
    assert recent[0]["outcome"] == "approved"


def test_approval_deny_blocks_the_tool(isolated):
    _, r, recent = _overwrite_chat(isolated, "deny")
    assert r.status_code == 200
    assert (isolated / "workspace" / "note.txt").read_text(encoding="utf-8") == "old"
    assert recent[0]["outcome"] == "denied"


def test_approval_timeout_denies(isolated):
    c, r, _ = _overwrite_chat(isolated, None, timeout=0.3)
    assert r.status_code == 200
    assert (isolated / "workspace" / "note.txt").read_text(encoding="utf-8") == "old"
    assert c.get("/api/approvals", headers=H).json()["recent"][0]["outcome"] == "timeout"


def test_approval_needs_matching_argument_hash(isolated):
    _, _, recent = _overwrite_chat(isolated, "approve", wrong_hash=True)
    assert (isolated / "workspace" / "note.txt").read_text(encoding="utf-8") == "old"
    assert recent[0]["outcome"] == "denied"


def test_unknown_approval_404(client):
    assert client.post("/api/approvals/999", headers=H, json={"decision": "deny"}).status_code == 404


# ---- chat ----

def test_chat_roundtrip_marathi(client):
    sid = client.post("/api/chat/sessions", headers=H).json()["id"]
    r = client.post(f"/api/chat/sessions/{sid}/messages", headers=H, json={"text": "नमस्कार Jarvis"})
    assert r.json()["reply"] == "Good evening, sir."
    assert client.post(f"/api/chat/sessions/{sid}/end", headers=H).json()["ended"] is True
    assert client.post(f"/api/chat/sessions/{sid}/messages", headers=H, json={"text": "hi"}).status_code == 404


# ---- memory ----

def _seed_memories():
    rt = open_runtime()
    try:
        a = rt.memory.save(Memory(name="Tea preference", body="Likes masala tea", evidence="I like masala tea",
                                  summary_en="Prefers masala tea"))
        b = rt.memory.save(Memory(name="Clinic visit", body="Example clinic on Monday", evidence="clinic Monday",
                                  sensitivity="sensitive", summary_en="Clinic visit Monday"))
        return a.id, b.id
    finally:
        rt.close()


def test_memory_list_masks_sensitive(client):
    normal, sensitive = _seed_memories()
    items = {m["id"]: m for m in client.get("/api/memory", headers=H).json()["items"]}
    assert items[normal]["body"] == "Likes masala tea" and not items[normal]["masked"]
    assert items[sensitive]["masked"] and items[sensitive]["body"] == "" and "Clinic" not in str(items[sensitive])
    assert "Clinic" not in client.get(f"/api/memory/{sensitive}", headers=H).text
    shown = client.post(f"/api/memory/{sensitive}/reveal", headers=H).json()
    assert shown["body"] == "Example clinic on Monday" and not shown["masked"]


def test_memory_search_edit_archive(client):
    normal, _ = _seed_memories()
    hits = client.get("/api/memory", params={"q": "masala"}, headers=H).json()["items"]
    assert [h["id"] for h in hits] == [normal]
    r = client.patch(f"/api/memory/{normal}", headers=H, json={"body": "Likes ginger tea"})
    assert r.status_code == 200 and r.json()["body"] == "Likes ginger tea"
    bad = client.patch(f"/api/memory/{normal}", headers=H, json={"body": "password is hunter2"})
    assert bad.status_code == 400
    assert client.patch(f"/api/memory/{normal}", headers=H, json={"sensitivity": "secret"}).status_code == 422
    assert client.post(f"/api/memory/{normal}/archive", headers=H).json()["status"] == "archived"
    assert normal not in [m["id"] for m in client.get("/api/memory", headers=H).json()["items"]]
    assert client.get("/api/memory/m-9999", headers=H).status_code == 404


# ---- connectors registry ----

def _tool(c, name):
    return next(t for t in c.get("/api/connectors", headers=H).json()["tools"] if t["name"] == name)


def test_lowering_a_tier_is_refused(client):
    assert _tool(client, "delete_file")["tier"] == "T3"
    r = client.patch("/api/connectors/tools/delete_file", headers=H, json={"tier": "T1"})
    assert r.status_code == 403 and "lowering" in r.json()["detail"]
    assert _tool(client, "delete_file")["tier"] == "T3"


def test_raise_then_lower_back_refused_and_disable(client, isolated):
    r = client.patch("/api/connectors/tools/write_file", headers=H, json={"tier": "T2"})
    assert r.status_code == 200 and r.json()["tier"] == "T2" and r.json()["builtin_tier"] == "T1"
    assert client.patch("/api/connectors/tools/write_file", headers=H, json={"tier": "T1"}).status_code == 403
    r = client.patch("/api/connectors/tools/weather", headers=H, json={"enabled": False})
    assert r.json()["enabled"] is False
    assert client.patch("/api/connectors/tools/weather", headers=H, json={"enabled": True}).status_code == 403
    text = (isolated / "connectors" / "registry.yaml").read_text(encoding="utf-8")
    assert "enabled: false" in text
    assert client.patch("/api/connectors/tools/nope", headers=H, json={"tier": "T3"}).status_code == 404


def test_tier_edit_reaches_chat(isolated):
    """A tool raised to T4 from the dashboard never runs in a chat."""
    script = [{"tool": "weather", "arguments": {"place": "Pune"}}, "ok"]
    with _client(factory=Scripted(script)) as c:
        c.patch("/api/connectors/tools/weather", headers=H, json={"tier": "T4"})
        sid = c.post("/api/chat/sessions", headers=H).json()["id"]
        c.post(f"/api/chat/sessions/{sid}/messages", headers=H, json={"text": "weather?"})
        runs = c.get("/api/agents", headers=H).json()["runs"]
        assert runs[0]["tool"] == "weather" and runs[0]["ok"] is False and runs[0]["tier"] == "T4"


# ---- tasks ----

class _Runner:
    def __init__(self, rt):
        from jarvis.core.runtime import task_store
        self.ts = task_store(rt)

    def run(self, task_id):
        self.ts.set_state(task_id, "PLANNED")
        self.ts.set_state(task_id, "RUNNING")
        self.ts.set_state(task_id, "VERIFYING")
        return self.ts.set_state(task_id, "COMPLETED")


def test_task_create_run_show_cancel(isolated):
    settings = WebSettings(provider="fake")
    app = create_app(settings, TOKEN, task_runner_factory=lambda rt, approver, progress: _Runner(rt),
                     allowed_hosts=["testserver"], trusted_clients={"testclient"}, static_dir=None)
    with TestClient(app) as c:
        tid = c.post("/api/tasks", headers=H, json={"goal": "Compare two example laptops"}).json()["id"]
        other = c.post("/api/tasks", headers=H, json={"goal": "Another task", "priority": "low"}).json()["id"]
        assert c.post(f"/api/tasks/{tid}/run", headers=H).json()["started"] is True
        app.state.tasks.join(tid, 5)
        d = c.get(f"/api/tasks/{tid}", headers=H).json()
        assert d["state"] == "COMPLETED" and [e["kind"] for e in d["events"]][0] == "created"
        assert c.post(f"/api/tasks/{tid}/run", headers=H).status_code == 409
        assert c.post(f"/api/tasks/{other}/cancel", headers=H).json()["state"] == "CANCELLED"
        assert c.post(f"/api/tasks/{other}/cancel", headers=H).status_code == 409
        states = {t["id"]: t["state"] for t in c.get("/api/tasks", headers=H).json()["items"]}
        assert states == {tid: "COMPLETED", other: "CANCELLED"}
        assert c.get("/api/tasks/t-999", headers=H).status_code == 404


def test_task_run_refused_while_stopped(client):
    tid = client.post("/api/tasks", headers=H, json={"goal": "x"}).json()["id"]
    client.post("/api/stop", headers=H, json={"engaged": True})
    assert client.post(f"/api/tasks/{tid}/run", headers=H).status_code == 409


def test_task_approval_routes_to_queue(isolated):
    """A task thread asking for approval shows up in the queue with its task id."""
    from jarvis.control.approvals import ApprovalRequest

    seen = {}

    class AskingRunner:
        def __init__(self, approver):
            self.approver = approver

        def run(self, task_id):
            seen["answer"] = self.approver(ApprovalRequest("open_url", "T2", {"url": "https://example.com"}, "x"))

    app = create_app(WebSettings(provider="fake"), TOKEN,
                     task_runner_factory=lambda rt, approver, progress: AskingRunner(approver),
                     allowed_hosts=["testserver"], trusted_clients={"testclient"}, static_dir=None)
    with TestClient(app) as c:
        tid = c.post("/api/tasks", headers=H, json={"goal": "open a page", "run": True}).json()["id"]
        p = _wait_pending(c)[0]
        assert p["task_id"] == tid and p["source"] == f"task:{tid}"
        c.post(f"/api/approvals/{p['id']}", headers=H, json={"decision": "approve", "args_sha256": p["args_sha256"]})
        app.state.tasks.join(tid, 5)
        assert seen["answer"] is True


# ---- agents, usage, settings, schedules ----

def test_usage_agents_settings_schedules(client):
    sid = client.post("/api/chat/sessions", headers=H).json()["id"]
    client.post(f"/api/chat/sessions/{sid}/messages", headers=H, json={"text": "hello"})
    u = client.get("/api/usage", headers=H).json()
    assert u["totals"]["calls"] == 1 and u["items"][0]["route"] == "main_chat" and u["items"][0]["model"] == "fake-1"
    a = client.get("/api/agents", headers=H).json()
    assert a["by_route"][0]["route"] == "main_chat"
    s = client.get("/api/settings", headers=H).json()
    assert s["stop"]["engaged"] is False and "main_chat" in [r["route"] for r in s["routes"]]
    sw = s["cloud"]["switch"]  # wired to jarvis/web/hooks.py since all phases are merged
    assert sw["installed"] is True and sw["wired"] is True and sw["source"] == "config"
    sch = client.get("/api/schedules", headers=H).json()
    assert sch["installed"] is True and sch["wired"] is True and sch["items"] == []


def test_root_without_build_explains(client):
    r = client.get("/")
    assert r.status_code == 200 and "npm run build" in r.text


def test_repeat_works_in_the_dashboard_chat_and_saves_only_after_yes(isolated):
    """/repeat in the dashboard chat behaves like the terminal: a draft first, saved only on /repeat yes."""
    with _client(Scripted(script=["No action yet."])) as client:
        sid = client.post("/api/chat/sessions", headers=H).json()["id"]
        r = client.post(f"/api/chat/sessions/{sid}/messages", headers=H, json={"text": "/repeat"}).json()
        assert r["kind"] == "command" and "Usage: /repeat" in r["reply"]
        r = client.post(f"/api/chat/sessions/{sid}/messages", headers=H, json={"text": "/repeat no"}).json()
        assert r["kind"] == "command" and "Nothing is waiting" in r["reply"]


def test_why_works_in_the_dashboard_chat(isolated):
    with _client(Scripted(script=["Hello, sir."])) as client:
        sid = client.post("/api/chat/sessions", headers=H).json()["id"]
        r = client.post(f"/api/chat/sessions/{sid}/messages", headers=H, json={"text": "/why"}).json()
        assert r["kind"] == "command" and "Nothing to explain yet" in r["reply"]
        client.post(f"/api/chat/sessions/{sid}/messages", headers=H, json={"text": "hello"})
        r = client.post(f"/api/chat/sessions/{sid}/messages", headers=H, json={"text": "/why"}).json()
        assert r["kind"] == "command" and "Context Jarvis had for its last answer" in r["reply"]
