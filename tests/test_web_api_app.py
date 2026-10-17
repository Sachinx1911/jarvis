import importlib.util
"""Dashboard endpoints that make Jarvis usable without a terminal: projects and documents,
teach-by-demonstration, schedules and reminders, setup (secrets never echoed), interview,
evaluation, voice. Offline: fake provider, fake speech engines, fake Google flow."""

import io
import json
import wave

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from jarvis.core.runtime import make_chat  # noqa: E402
from jarvis.providers.fake import FakeProvider  # noqa: E402
from jarvis.web.app import create_app  # noqa: E402
from jarvis.web.settings import WebSettings  # noqa: E402
needs_numpy = pytest.mark.skipif(importlib.util.find_spec("numpy") is None,
                                 reason="numpy comes with the optional [voice] extra")


TOKEN = "test-token-not-real"
H = {"X-Jarvis-Token": TOKEN}
SECRET = "tvly-THIS-IS-A-FAKE-SECRET-123"


class Scripted:
    def __init__(self, script=None):
        self.provider = FakeProvider(script=script or [])

    def __call__(self, rt, approver):
        session = make_chat(rt, "fake", approver)
        session.provider = session.loop.provider = self.provider
        return session


@pytest.fixture
def cfgdir(tmp_path):
    d = tmp_path / "cfg"
    d.mkdir()
    return d


def _proactive():
    from jarvis.proactive.notify import ConsoleNotifier
    from jarvis.proactive.service import Proactive
    from jarvis.proactive.settings import load_settings

    return Proactive(load_settings(), notifier=ConsoleNotifier(io.StringIO()), provider_override="fake")


def _client(cfgdir, **kw) -> TestClient:
    settings = WebSettings(approval_timeout_s=5, provider="fake")
    app = create_app(settings, TOKEN, chat_factory=kw.pop("factory", Scripted()), allowed_hosts=["testserver"],
                     trusted_clients={"testclient"}, static_dir=None, config_dir=cfgdir,
                     proactive_factory=kw.pop("proactive", _proactive), **kw)
    return TestClient(app)


@pytest.fixture
def client(isolated, cfgdir):
    with _client(cfgdir) as c:
        yield c


def audit_text(home) -> str:
    path = home / "data" / "audit.jsonl"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def wav(seconds=1.0, rate=16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x10\x00" * int(rate * seconds))
    return buf.getvalue()


# ---- every new endpoint needs the token ----

@pytest.mark.parametrize("method,path", [
    ("get", "/api/projects"), ("post", "/api/projects"), ("get", "/api/docs/search?q=x"),
    ("get", "/api/teach"), ("post", "/api/teach/start"), ("get", "/api/schedules/all"),
    ("post", "/api/schedules/draft"), ("post", "/api/schedules/confirm"), ("get", "/api/reminders"),
    ("get", "/api/unattended"), ("get", "/api/brief"), ("get", "/api/setup"), ("post", "/api/setup/secret"),
    ("post", "/api/setup/config"), ("post", "/api/setup/google-auth"), ("get", "/api/setup/health"),
    ("get", "/api/interview"), ("post", "/api/eval"), ("post", "/api/voice/transcribe"),
    ("post", "/api/projects/demo/docs?filename=a.md"), ("post", "/api/app/quit"),
])
def test_new_endpoints_need_token(client, method, path):
    assert getattr(client, method)(path).status_code == 401


def test_new_endpoints_refuse_foreign_origin(client):
    r = client.post("/api/setup/secret", headers={**H, "Origin": "https://evil.example"},
                    json={"name": "tavily_api_key", "value": SECRET})
    assert r.status_code == 403
    from jarvis.secrets import get_secret

    assert get_secret("tavily_api_key") is None


# ---- projects and documents ----

def test_project_create_edit_upload_index_search(client, isolated):
    r = client.post("/api/projects", headers=H, json={"name": "Demo Trip", "goal": "Plan a made-up trip"})
    assert r.json() == {"name": "demo-trip", "created": True}
    items = client.get("/api/projects", headers=H).json()["items"]
    assert items[0]["name"] == "demo-trip" and items[0]["goal"] == "Plan a made-up trip"

    show = client.get("/api/projects/demo-trip", headers=H).json()
    assert "## Goal" in show["project_md"]
    md = show["project_md"] + "\n## Notes\nTrain at 06:15.\n"
    assert client.put("/api/projects/demo-trip/md", headers=H, json={"text": md}).json()["saved"]
    assert "Train at 06:15" in (isolated / "projects" / "demo-trip" / "PROJECT.md").read_text(encoding="utf-8")

    body = "# Trip notes\n\n## Train\nThe train to the beach leaves at 06:15 on 14 December.\nपुणे ते गोवा.\n"
    r = client.post("/api/projects/demo-trip/docs?filename=trip-notes.md", headers=H, content=body.encode("utf-8"))
    assert r.status_code == 200, r.text
    assert r.json()["file"] == "trip-notes.md" and "1 added" in r.json()["index"]
    docs = client.get("/api/projects/demo-trip", headers=H).json()["documents"]
    assert docs[0]["file"] == "trip-notes.md" and docs[0]["indexed"] and docs[0]["privacy"] == "P2"

    hits = client.get("/api/docs/search", headers=H, params={"q": "train", "project": "demo-trip"}).json()["items"]
    assert hits and hits[0]["citation"].startswith("trip-notes.md") and "06:15" in hits[0]["text"]
    assert client.get("/api/docs/search", headers=H, params={"q": "गोवा"}).json()["items"]

    r = client.post("/api/projects/demo-trip/privacy", headers=H, json={"file": "trip-notes.md", "privacy": "P1"})
    assert r.json()["privacy"] == "P1"
    docs = client.get("/api/projects/demo-trip", headers=H).json()["documents"]
    assert docs[0]["privacy"] == "P1"
    assert client.post("/api/projects/demo-trip/index", headers=H, json={"force": True}).status_code == 200
    log = audit_text(isolated)
    for event in ("project_created", "project_md_edited", "document_uploaded", "docs_index", "docs_mark"):
        assert event in log


def test_upload_existing_file_needs_replace(client):
    client.post("/api/projects", headers=H, json={"name": "p1"})
    url = "/api/projects/p1/docs?filename=a.txt"
    assert client.post(url, headers=H, content=b"one").status_code == 200
    assert client.post(url, headers=H, content=b"two").status_code == 409
    assert client.post(url + "&replace=true", headers=H, content=b"two").status_code == 200


@pytest.mark.parametrize("name", ["../../evil.md", "..\\..\\evil.md", "/etc/evil.md", "C:\\Windows\\evil.md",
                                  "docs/../../../evil.md", "%2e%2e%2fevil.md"])
def test_upload_path_traversal_is_blocked(client, isolated, name):
    client.post("/api/projects", headers=H, json={"name": "p1"})
    r = client.post("/api/projects/p1/docs", headers=H, params={"filename": name}, content=b"hello")
    docs = isolated / "projects" / "p1" / "docs"
    if r.status_code == 200:  # accepted only as a plain name inside docs/
        saved = docs / r.json()["file"]
        assert saved.is_file() and saved.parent.resolve() == docs.resolve()
        assert "/" not in r.json()["file"] and "\\" not in r.json()["file"] and ".." not in r.json()["file"]
    assert not (isolated / "evil.md").exists() and not (isolated / "projects" / "evil.md").exists()
    assert not (isolated / "projects" / "p1" / "evil.md").exists()


def test_upload_type_and_content_checks(client):
    client.post("/api/projects", headers=H, json={"name": "p1"})
    up = lambda name, data: client.post("/api/projects/p1/docs", headers=H, params={"filename": name}, content=data)  # noqa: E731
    assert up("run.exe", b"MZ").status_code == 400
    assert up("notes.html", b"<script>").status_code == 400
    assert up("fake.pdf", b"not a pdf").status_code == 400
    assert up("fake.docx", b"not a zip").status_code == 400
    assert up("bin.txt", b"\xff\xfe\x00bad").status_code == 400
    assert up("empty.md", b"").status_code == 400
    assert up("noext", b"hello").status_code == 400
    r = up("con.txt", b"device name")
    assert r.status_code == 200 and r.json()["file"] == "_con.txt"
    r = up("मराठी नोंद.md", "नमस्कार".encode("utf-8"))
    assert r.status_code == 200 and r.json()["file"] == "मराठी नोंद.md"


def test_upload_size_limit(client, monkeypatch):
    from jarvis.web import routes_projects

    monkeypatch.setattr(routes_projects, "MAX_UPLOAD_BYTES", 10)
    client.post("/api/projects", headers=H, json={"name": "p1"})
    r = client.post("/api/projects/p1/docs", headers=H, params={"filename": "big.txt"}, content=b"x" * 50)
    assert r.status_code == 413


def test_unknown_or_bad_project_names(client):
    assert client.get("/api/projects/nope", headers=H).status_code == 404
    assert client.get("/api/projects/..%2F..", headers=H).status_code in (400, 404)
    r = client.post("/api/projects/nope/docs", headers=H, params={"filename": "a.md"}, content=b"x")
    assert r.status_code == 404


def test_chat_active_project(client):
    client.post("/api/projects", headers=H, json={"name": "demo-trip"})
    s = client.post("/api/chat/sessions", headers=H, json={"project": "demo-trip"}).json()
    assert s["project"] == "demo-trip"
    assert client.post(f"/api/chat/sessions/{s['id']}/project", headers=H, json={"project": None}).json()["project"] is None
    assert client.post(f"/api/chat/sessions/{s['id']}/project", headers=H, json={"project": "nope"}).status_code == 400
    r = client.post(f"/api/chat/sessions/{s['id']}/messages", headers=H, json={"text": "/project demo-trip"})
    assert r.json()["kind"] == "command" and r.json()["project"] == "demo-trip"
    assert [c["project"] for c in client.get("/api/chat/sessions", headers=H).json()] == ["demo-trip"]
    r = client.post(f"/api/chat/sessions/{s['id']}/messages", headers=H, json={"text": "/task do a thing"})
    assert "Tasks tab" in r.json()["reply"]


# ---- teach by demonstration ----

DRAFT = {"name": "daily note", "description": "Create a daily note file", "inputs": [
    {"name": "date", "description": "the day"}], "preconditions": [], "steps": [
    {"text": "Create notes/day-{date}.md with headings Plan, Done, Ideas", "tool": "write_file"}],
    "verify": ["the file exists"]}


def test_teach_flow_record_draft_edit_approve(client, isolated, monkeypatch):
    r = client.post("/api/teach/start", headers=H, json={"name": "daily note"})
    rid = r.json()["id"]
    assert client.post("/api/teach/start", headers=H, json={"name": "again"}).status_code == 409
    assert client.post("/api/teach/note", headers=H, json={"text": "I plan every morning"}).json()["noted"]
    assert client.get("/api/teach", headers=H).json()["active"]["id"] == rid
    assert client.post(f"/api/teach/recordings/{rid}/draft", headers=H).status_code == 409  # still recording
    ev = client.post("/api/teach/stop", headers=H).json()["evidence"]
    assert "I plan every morning" in ev

    # The draft is one model call through the provider layer; the fake provider returns DRAFT.
    import jarvis.providers as providers

    made = []

    def make_provider(name, config):
        made.append(name)
        return FakeProvider(script=[{"json": DRAFT}])

    monkeypatch.setattr(providers, "make_provider", make_provider)
    r = client.post(f"/api/teach/recordings/{rid}/draft", headers=H)
    assert r.status_code == 200, r.text
    draft = r.json()["draft"]
    assert draft.startswith("---") and "daily-note" in draft and made == ["fake"]

    assert client.put(f"/api/teach/recordings/{rid}/draft", headers=H, json={"text": "no front matter"}).status_code == 400
    edited = draft.replace("Create a daily note file", "Create my daily note file")
    assert client.put(f"/api/teach/recordings/{rid}/draft", headers=H, json={"text": edited}).json()["saved"]
    assert client.post(f"/api/teach/recordings/{rid}/approve", headers=H).json() == {"skill": "daily-note", "version": 1}
    # approving again keeps version 1 as SKILL.v1.md
    assert client.post(f"/api/teach/recordings/{rid}/approve", headers=H).json()["version"] == 2
    skills = client.get("/api/teach", headers=H).json()["skills"]
    assert skills[0]["name"] == "daily-note" and skills[0]["old_versions"] == ["SKILL.v1.md"]
    assert "my daily note" in client.get("/api/skills/daily-note", headers=H).json()["text"]
    assert client.get("/api/teach/recordings/../x", headers=H).status_code in (400, 404)
    assert client.get("/api/teach/recordings/r-zzzzzz", headers=H).status_code == 400
    log = audit_text(isolated)
    for event in ("recording_started", "recording_note", "recording_stopped", "skill_drafted", "skill_approved"):
        assert event in log


# ---- schedules, reminders, unattended approvals, brief ----

def test_schedule_saved_only_after_confirm(client):
    r = client.post("/api/schedules/draft", headers=H,
                    json={"text": "every day at 21:00 summarize my tasks", "use_model": False})
    d = r.json()
    assert d["draft_id"] and d["draft"]["cron"] and "Next:" in d["show"]
    assert client.get("/api/schedules/all", headers=H).json()["items"] == []  # nothing saved yet
    saved = client.post("/api/schedules/confirm", headers=H, json={"draft_id": d["draft_id"]}).json()["saved"]
    items = client.get("/api/schedules/all", headers=H).json()["items"]
    assert [s["id"] for s in items] == [saved["id"]] and items[0]["source"] == "dashboard"
    # the same draft cannot be saved twice; an invented id saves nothing
    assert client.post("/api/schedules/confirm", headers=H, json={"draft_id": d["draft_id"]}).status_code == 404
    assert client.post("/api/schedules/confirm", headers=H, json={"draft_id": "0" * 24}).status_code == 404
    assert len(client.get("/api/schedules/all", headers=H).json()["items"]) == 1


def test_schedule_unreadable_text_asks_a_question(client):
    r = client.post("/api/schedules/draft", headers=H, json={"text": "sometime maybe", "use_model": False}).json()
    assert r["draft_id"] is None and r["question"]


def test_schedule_pause_resume_runs_delete(client, isolated):
    d = client.post("/api/schedules/draft", headers=H,
                    json={"text": "every Monday at 9 project summary", "use_model": False}).json()
    sid = client.post("/api/schedules/confirm", headers=H, json={"draft_id": d["draft_id"]}).json()["saved"]["id"]
    assert client.post(f"/api/schedules/{sid}/pause", headers=H).json()["done"] == "pause"
    assert client.get(f"/api/schedules/{sid}/runs", headers=H).json()["enabled"] is False
    client.post(f"/api/schedules/{sid}/resume", headers=H)
    assert client.get(f"/api/schedules/{sid}/runs", headers=H).json()["enabled"] is True
    assert client.post(f"/api/schedules/{sid}/explode", headers=H).status_code == 422
    assert client.post("/api/schedules/s-999/pause", headers=H).status_code == 404
    client.post(f"/api/schedules/{sid}/delete", headers=H)        # law 2: archives, nothing deleted
    assert client.get("/api/schedules/all", headers=H).json()["items"] == []
    assert "schedule_pause" in audit_text(isolated) and "schedule_archive" in audit_text(isolated)
    assert "schedule_delete" not in audit_text(isolated)


def test_schedule_run_now_is_a_background_job(isolated, cfgdir):
    from jarvis.proactive.scheduler import RunResult

    class Runner:
        def run(self, sid, trigger):
            return RunResult(sid, 1, "ok", "the summary")

    def proactive():
        p = _proactive()
        p.runner = lambda: Runner()
        return p

    with _client(cfgdir, proactive=proactive) as c:
        d = c.post("/api/schedules/draft", headers=H, json={"text": "every day at 7 hello", "use_model": False}).json()
        sid = c.post("/api/schedules/confirm", headers=H, json={"draft_id": d["draft_id"]}).json()["saved"]["id"]
        assert c.post(f"/api/schedules/{sid}/run-now", headers=H).json()["started"]
        c.app.state.ctx.jobs.join("schedule-run", 5)
        job = c.get("/api/schedules/all", headers=H).json()["job"]
        assert job["status"] == "done" and job["result"]["text"] == "the summary"


def test_reminders_add_list_cancel(client):
    r = client.post("/api/reminders", headers=H, json={"text": "in 10 minutes drink water"})
    assert r.status_code == 200 and r.json()["text"] == "drink water"
    rid = r.json()["id"]
    assert [x["id"] for x in client.get("/api/reminders", headers=H).json()["items"]] == [rid]
    assert client.post(f"/api/reminders/{rid}/cancel", headers=H).json()["cancelled"]
    assert client.get("/api/reminders", headers=H).json()["items"] == []
    assert client.post(f"/api/reminders/{rid}/cancel", headers=H).status_code == 404
    assert client.post("/api/reminders", headers=H, json={"text": "drink water"}).status_code == 400


def test_unattended_approvals_need_matching_hash(client, isolated):
    from jarvis.control.approvals import ApprovalRequest
    from jarvis.core.runtime import open_runtime
    from jarvis.proactive.scheduler import PendingApprovals
    from datetime import datetime, timezone

    rt = open_runtime()
    try:
        pid = PendingApprovals(rt.store.conn).add("s-001", None, ApprovalRequest(
            "write_file", "T2", {"path": "notes/x.txt", "content": "made-up"}, "unattended"), datetime.now(timezone.utc))
    finally:
        rt.close()
    items = client.get("/api/unattended", headers=H).json()["items"]
    assert items[0]["id"] == pid and len(items[0]["args_sha256"]) == 64
    r = client.post(f"/api/unattended/{pid}", headers=H, json={"decision": "approve", "args_sha256": "0" * 64})
    assert r.status_code == 409
    r = client.post(f"/api/unattended/{pid}", headers=H, json={"decision": "deny"})
    assert r.json()["status"] == "denied"
    assert client.get("/api/unattended", headers=H).json()["items"] == []
    assert client.post(f"/api/unattended/{pid}", headers=H, json={"decision": "deny"}).status_code == 409


def test_brief(client):
    text = client.get("/api/brief", headers=H).json()["text"]
    assert isinstance(text, str) and text


# ---- setup: secrets are never echoed ----

def test_secret_set_never_echoed_or_logged(client, isolated):
    from jarvis.secrets import get_secret

    r = client.post("/api/setup/secret", headers=H, json={"name": "tavily_api_key", "value": SECRET})
    assert r.status_code == 200 and SECRET not in r.text and r.json() == {"name": "tavily_api_key", "set": True}
    assert get_secret("tavily_api_key") == SECRET
    status = client.get("/api/setup", headers=H)
    assert status.json()["secrets"]["tavily_api_key"] is True and SECRET not in status.text
    for path in ("/api/setup/health", "/api/settings", "/api/connectors"):
        assert SECRET not in client.get(path, headers=H).text, path
    assert SECRET not in audit_text(isolated) and "secret_set" in audit_text(isolated)


def test_secret_errors_do_not_echo_the_value(client):
    # unknown name: refused, and the 422 body has no "input" with the value
    r = client.post("/api/setup/secret", headers=H, json={"name": "anthropic_api_key", "value": SECRET})
    assert r.status_code == 422 and SECRET not in r.text
    r = client.post("/api/setup/secret", headers=H, json={"name": "tavily_api_key", "value": SECRET * 40})
    assert r.status_code == 422 and SECRET not in r.text
    r = client.post("/api/setup/secret", headers=H, json={"name": "dashboard_token", "value": "x"})
    assert r.status_code == 422


def test_config_written_to_local_yaml_merging(client, cfgdir):
    import yaml

    (cfgdir / "local.yaml").write_text("routing_file:\n  cloud_allowed: true\nproactive_file:\n  timezone: Asia/Kolkata\n",
                                       encoding="utf-8")
    r = client.post("/api/setup/config", headers=H, json={"telegram_allowed_user_id": 12345, "weather_place": "Pune"})
    assert r.status_code == 200, r.text
    data = yaml.safe_load((cfgdir / "local.yaml").read_text(encoding="utf-8"))
    assert data["routing_file"] == {"cloud_allowed": True}  # other settings kept
    assert data["proactive_file"]["timezone"] == "Asia/Kolkata"
    assert data["proactive_file"]["telegram"]["allowed_user_id"] == 12345
    assert data["proactive_file"]["brief"]["place"] == "Pune" and data["tools_file"]["weather"]["default_place"] == "Pune"
    assert (cfgdir / "local.yaml.bak").exists()
    assert client.get("/api/setup", headers=H).json()["config"] == {"telegram_allowed_user_id": 12345,
                                                                     "weather_place": "Pune"}
    assert client.post("/api/setup/config", headers=H, json={"weather_place": "Pune\nevil: 1"}).status_code == 400
    assert client.post("/api/setup/config", headers=H, json={"telegram_allowed_user_id": -5}).status_code == 422
    assert client.post("/api/setup/config", headers=H, json={}).status_code == 400


def test_config_refuses_broken_local_yaml(client, cfgdir):
    (cfgdir / "local.yaml").write_text("- just\n- a list\n", encoding="utf-8")
    assert client.post("/api/setup/config", headers=H, json={"weather_place": "Pune"}).status_code == 409
    assert (cfgdir / "local.yaml").read_text(encoding="utf-8") == "- just\n- a list\n"


def test_google_auth_without_client_file_explains(client):
    r = client.post("/api/setup/google-auth", headers=H).json()
    assert r["started"] is False and r["detail"]


def test_google_auth_runs_the_flow_in_background(isolated, cfgdir, tmp_path, monkeypatch):
    from jarvis.connectors.google import auth as google_auth

    secret_file = tmp_path / "client.json"
    secret_file.write_text(json.dumps({"installed": {"client_id": "made-up.apps.example", "client_secret": "x"}}),
                           encoding="utf-8")
    monkeypatch.setattr("jarvis.connectors.config.load_connectors_config",
                        lambda *a, **k: {"google": {"client_secret_file": str(secret_file)}})

    class Creds:
        refresh_token = "made-up-refresh"
        scopes = google_auth.SCOPES

    class Flow:
        def run_local_server(self, **kw):
            return Creds()

    with _client(cfgdir, oauth_flow_factory=lambda path, scopes: Flow()) as c:
        r = c.post("/api/setup/google-auth", headers=H).json()
        assert r["started"] is True
        c.app.state.ctx.jobs.join("google-auth", 5)
        job = c.get("/api/setup", headers=H).json()["google"]["job"]
        assert job["status"] == "done" and job["result"]["ok"] is True
        assert "made-up-refresh" not in c.get("/api/setup", headers=H).text


def test_health_and_setup_status(client):
    h = client.get("/api/setup/health", headers=H).json()
    assert {p["name"] for p in h["providers"]} == {"claude_code", "anthropic", "fake"}
    assert any(c["name"] == "tavily key" for c in h["connectors"])
    s = client.get("/api/setup", headers=H).json()
    assert s["voice"]["stt_model_mb"] > 0 and "jarvis voice setup" in s["voice"]["stt_setup"]
    assert s["can_quit"] is False


# ---- interview and evaluation ----

def test_interview_answers_become_memories(client, isolated):
    qs = client.get("/api/interview", headers=H).json()["questions"]
    assert len(qs) >= 5
    r = client.post("/api/interview/answer", headers=H, json={"question": qs[0], "answer": "Call me Sam; मराठी आणि English"})
    assert r.status_code == 200, r.text
    assert r.json()["id"].startswith("m-")
    assert client.post("/api/interview/answer", headers=H, json={"question": "made up?", "answer": "x"}).status_code == 400
    r = client.post("/api/interview/answer", headers=H, json={"question": qs[0], "answer": "my password: abc123"})
    assert r.status_code == 400
    assert "interview_answer" in audit_text(isolated)


def test_eval_runs_in_background(client, monkeypatch):
    from jarvis.evals import runner

    def fake_suite(rt, provider_name=None, category=None):
        rep = runner.Report("fake", "fake-model")
        rep.results.append(runner.TaskResult("t1", "memory", "mr", True, "ok"))
        return rep

    monkeypatch.setattr(runner, "run_suite", fake_suite)
    assert client.post("/api/eval", headers=H, json={}).json()["started"]
    client.app.state.ctx.jobs.join("eval", 5)
    job = client.get("/api/eval", headers=H).json()["job"]
    assert job["status"] == "done" and job["result"]["passed"] == 1 and job["result"]["total"] == 1


# ---- voice ----

@needs_numpy
def test_voice_not_installed_message(isolated, cfgdir):
    from jarvis.voice.base import VoiceUnavailable

    class Missing:
        name = "faster_whisper"

        def check(self):
            raise VoiceUnavailable("faster-whisper is not installed")

        def transcribe(self, audio, hint=None):
            raise AssertionError("not reached")

    with _client(cfgdir, stt_factory=Missing) as c:
        assert c.get("/api/voice/status", headers=H).json()["stt_ready"] is False
        r = c.post("/api/voice/transcribe", headers=H, content=wav())
        assert r.status_code == 503 and "speech-to-text not installed (run voice setup)" in r.json()["detail"]


@needs_numpy
def test_voice_transcribe_and_unclear(isolated, cfgdir):
    from jarvis.voice.base import Transcript
    from jarvis.voice.stt import FakeSTT

    stt = FakeSTT(["नमस्कार जार्विस", Transcript("mumble", "en", 0.1)])
    with _client(cfgdir, stt_factory=lambda: stt) as c:
        r = c.post("/api/voice/transcribe", headers=H, content=wav()).json()
        assert r["status"] == "ok" and r["text"] == "नमस्कार जार्विस"
        r = c.post("/api/voice/transcribe", headers=H, content=wav()).json()
        assert r["status"] == "unclear" and r["text"] == ""
        assert c.post("/api/voice/transcribe", headers=H, content=b"not a wav").status_code == 400
        assert c.post("/api/voice/transcribe", headers=H, content=wav(rate=4000)).status_code == 400


def test_speak_reply_uses_local_tts_and_withholds_p3(isolated, cfgdir):
    from jarvis.voice.tts import FakeTTS, SpeechOutput

    tts = FakeTTS()
    factory = Scripted(script=["Your code is password: hunter2"])
    with _client(cfgdir, factory=factory, speech_factory=lambda: SpeechOutput(tts)) as c:
        s = c.post("/api/chat/sessions", headers=H).json()
        r = c.post(f"/api/chat/sessions/{s['id']}/messages", headers=H, json={"text": "hi", "speak": True}).json()
        assert r["voice"]["spoken"] is True and r["voice"]["engine"] == "fake"
        assert tts.spoken and "hunter2" not in tts.spoken[0][0]


def test_microphone_allowed_for_own_page_only(client):
    assert "microphone=(self)" in client.get("/api/health", headers=H).headers["permissions-policy"]


def test_quit_only_under_app(isolated, cfgdir):
    called = []
    with _client(cfgdir, on_quit=lambda: called.append(1)) as c:
        assert c.post("/api/app/quit", headers=H).json()["quitting"] and called == [1]


class FakeWake:
    """Stands in for the wake-word model: says where in the clip "hey Jarvis" ended."""

    threshold = 0.25

    def __init__(self, score: float, end_seconds: float):
        self.score, self.end = score, end_seconds
        self.scanned = 0

    def scan(self, pcm: bytes):
        self.scanned += 1
        return self.score, int(self.end * 16000) * 2


@needs_numpy
def test_hands_free_wake_cuts_the_wake_phrase_before_transcribing(isolated, cfgdir):
    from jarvis.voice.stt import FakeSTT

    stt = FakeSTT(["आज काय काम आहे"])
    seen = []
    orig = stt.transcribe
    stt.transcribe = lambda audio, hint=None: (seen.append(audio.seconds), orig(audio, hint))[1]
    wake = FakeWake(0.6, 0.8)
    with _client(cfgdir, stt_factory=lambda: stt, wake_factory=lambda: wake) as c:
        r = c.post("/api/voice/transcribe?wake=1", headers=H, content=wav(3.0)).json()
    assert r["status"] == "ok" and r["wake_hit"] is True and r["text"] == "आज काय काम आहे"
    assert abs(seen[0] - 2.2) < 0.01  # only the part after the wake phrase was transcribed


@needs_numpy
def test_hands_free_wake_alone_and_no_wake(isolated, cfgdir):
    from jarvis.voice.stt import FakeSTT

    stt = FakeSTT(["hello there"] * 3)
    with _client(cfgdir, stt_factory=lambda: stt, wake_factory=lambda: FakeWake(0.7, 1.8)) as c:
        r = c.post("/api/voice/transcribe?wake=1", headers=H, content=wav(2.0)).json()
        assert r["status"] == "wake_only" and r["wake_hit"] is True
    with _client(cfgdir, stt_factory=lambda: stt, wake_factory=lambda: FakeWake(0.05, 0.4)) as c:
        r = c.post("/api/voice/transcribe?wake=1", headers=H, content=wav(2.0)).json()
        assert r["status"] == "ok" and r["wake_hit"] is False and r["text"] == "hello there"
    wake = FakeWake(0.9, 0.5)
    with _client(cfgdir, stt_factory=lambda: stt, wake_factory=lambda: wake) as c:
        r = c.post("/api/voice/transcribe", headers=H, content=wav(2.0)).json()  # push-to-talk: no wake check
        assert "wake" not in r and wake.scanned == 0


@needs_numpy
def test_transcribe_accepts_the_microphone_rate_and_resamples(isolated, cfgdir):
    from jarvis.voice.stt import FakeSTT

    stt = FakeSTT(["namaskar"])
    seen = []
    orig = stt.transcribe
    stt.transcribe = lambda audio, hint=None: (seen.append((audio.sample_rate, round(audio.seconds, 1))), orig(audio, hint))[1]
    with _client(cfgdir, stt_factory=lambda: stt) as c:
        r = c.post("/api/voice/transcribe", headers=H, content=wav(1.0, rate=48000)).json()
    assert r["status"] == "ok" and seen == [(16000, 1.0)]


def test_speaking_status_and_stop(isolated, cfgdir):
    from jarvis.voice.tts import FakeTTS, SpeechOutput

    tts = FakeTTS("local", keep_playing=True)
    factory = Scripted(script=[{"text": "Good evening, sir."}])
    with _client(cfgdir, factory=factory, speech_factory=lambda: SpeechOutput(tts)) as c:
        assert c.get("/api/voice/speaking", headers=H).json() == {"speaking": False}
        s = c.post("/api/chat/sessions", headers=H, json={}).json()
        r = c.post(f"/api/chat/sessions/{s['id']}/messages", headers=H, json={"text": "hi", "speak": True}).json()
        assert r["voice"]["spoken"] is True
        assert c.get("/api/voice/speaking", headers=H).json() == {"speaking": True}
        assert c.post("/api/voice/stop", headers=H).json() == {"stopped": True}
        assert c.get("/api/voice/speaking", headers=H).json() == {"speaking": False}
        assert c.post("/api/voice/stop", headers=H).json() == {"stopped": False}
