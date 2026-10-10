"""Repeat-this in the dashboard: "Repeat this..." on a finished task shows the full draft and
saves only on the Save click for that exact draft; pending drafts from any channel can be
opened, saved or cancelled; expiry, the 30-minute minimum and the emergency stop still apply.
Offline: the skill draft comes from a scripted FakeProvider, schedules are read by rules,
the clock is fixed. All data is made up."""

import json
import time

import pytest

pytest.importorskip("fastapi")

from jarvis.control.stop import StopSwitch  # noqa: E402
from jarvis.core.runtime import open_runtime  # noqa: E402
from jarvis.db import Store  # noqa: E402
from jarvis.proactive.scheduler import ScheduleStore  # noqa: E402
from jarvis.providers.fake import FakeProvider  # noqa: E402
from jarvis.tasks import repeat as repeat_mod  # noqa: E402
from jarvis.tasks.repeat import RepeatProposal, RepeatStore  # noqa: E402
from jarvis.tasks.store import TaskStore  # noqa: E402
from jarvis.web.routes_repeat import draft_hash  # noqa: E402
from tests.test_proactive_support import at, proactive  # noqa: E402
from tests.test_web_api_app import H, _client, audit_text  # noqa: E402

NOW = at(2026, 10, 10, 15, 0)
DRAFT = {"name": "Weekly Price Check", "description": "Compare made-up laptop prices and save a report.",
         "inputs": [{"name": "date", "description": "the day, YYYY-MM-DD"}], "preconditions": [],
         "steps": [{"text": "Search prices for {date}", "tool": "web_search"},
                   {"text": "Write prices-{date}.md", "tool": "write_file"}],
         "verify": ["prices-{date}.md exists"]}
WITH_APPROVAL_STEPS = {**DRAFT, "steps": DRAFT["steps"] + [
    {"text": "Replace last week's summary", "tool": "overwrite_file"},
    {"text": "Send the contact form", "tool": "browser_submit"}]}


class Drafts(list):
    """The evidence each skill-draft call was given; .draft is what the fake model answers."""

    draft = DRAFT


@pytest.fixture
def drafts(monkeypatch):
    seen = Drafts()

    def fake_provider(name, config):
        class P(FakeProvider):
            def structured(self, req, schema):
                seen.append(req.messages[0].text_content())
                return super().structured(req, schema)
        return P(script=[{"json": seen.draft}])

    monkeypatch.setattr(repeat_mod, "make_provider", fake_provider)
    return seen


@pytest.fixture
def cfgdir(tmp_path):
    d = tmp_path / "cfg"
    d.mkdir()
    return d


@pytest.fixture
def client(isolated, cfgdir, drafts):
    with _client(cfgdir, proactive=lambda: proactive(NOW)) as c:
        yield c


def _task(home, goal="Compare made-up laptop prices", state="COMPLETED") -> str:
    store = Store(home / "data" / "jarvis.db")
    try:
        ts = TaskStore(store, home / "data" / "tasks")
        t = ts.create(goal)
        plan = {"mode": "answer", "use_team": False, "research": [], "acceptance_criteria": ["has prices"],
                "deliverable": {"filename": "result.md", "outline": "table"}, "solo_instructions": goal}
        store.conn.execute("UPDATE tasks SET state=?, plan=?, checkpoint=? WHERE id=?",
                           (state, json.dumps(plan), json.dumps({"report": "result.md"}), t.id))
        store.conn.execute("INSERT INTO tool_runs (task_id, tool, tier, arguments, result, ok, agent) VALUES "
                           "(?, 'web_search', 'T0', '{\"query\": \"laptop prices\"}', 'results', 1, 'jarvis')",
                           (t.id,))
        store.conn.commit()
        (ts.folder(t.id) / "result.md").write_text("| Laptop A | Rs 75,000 |", encoding="utf-8")
        return t.id
    finally:
        store.close()


def _schedules(home):
    store = Store(home / "data" / "jarvis.db")
    try:
        return ScheduleStore(store.conn).list()
    finally:
        store.close()


def _events(home) -> list[dict]:
    return [json.loads(line) for line in audit_text(home).splitlines()]


def _nothing_saved(home) -> bool:
    return _schedules(home) == [] and not (home / "skills" / "weekly-price-check").exists()


# ---- token and origin ----

@pytest.mark.parametrize("method,path", [
    ("get", "/api/repeat/drafts"), ("get", "/api/repeat/drafts/rp-000000"), ("post", "/api/repeat/propose"),
    ("post", "/api/repeat/drafts/rp-000000/save"), ("post", "/api/repeat/drafts/rp-000000/cancel"),
])
def test_repeat_routes_need_the_token(client, method, path):
    assert getattr(client, method)(path).status_code == 401


def test_save_refuses_a_foreign_origin_or_cross_site_request(client, isolated):
    tid = _task(isolated)
    d = client.post("/api/repeat/propose", headers=H, json={"task_id": tid, "when": "every Monday at 9"}).json()
    body = {"draft_sha256": d["draft_sha256"]}
    r = client.post(f"/api/repeat/drafts/{d['id']}/save", headers={**H, "Origin": "https://evil.example"}, json=body)
    assert r.status_code == 403
    r = client.post(f"/api/repeat/drafts/{d['id']}/save", headers={**H, "Sec-Fetch-Site": "cross-site"}, json=body)
    assert r.status_code == 403
    r = client.post("/api/repeat/propose", headers={**H, "Origin": "https://evil.example"},
                    json={"task_id": tid, "when": "every day at 9"})
    assert r.status_code == 403
    assert _nothing_saved(isolated) and len(client.get("/api/repeat/drafts", headers=H).json()["items"]) == 1


# ---- the flow on a finished task ----

def test_repeat_this_shows_the_full_draft_and_saves_only_on_save(client, isolated, drafts):
    tid = _task(isolated)
    r = client.post("/api/repeat/propose", headers=H, json={"task_id": tid, "when": "every Monday at 9"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["id"].startswith("rp-") and d["source"] == f"task {tid}" and d["origin"] == "task"
    assert "name: weekly-price-check" in d["skill_text"] and f"source: task {tid}" in d["skill_text"]
    assert d["schedule"]["cron"] == "0 9 * * mon" and d["schedule"]["target"] == "weekly-price-check"
    assert "--- SKILL.md draft ---" in d["show"] and "Cron: 0 9 * * mon" in d["show"]
    assert "Nothing is saved until you confirm this draft." in d["show"]
    assert d["held_steps"] == [] and d["skill_exists"] is False and len(d["draft_sha256"]) == 64
    assert 3500 < d["expires_in_s"] <= 3600
    assert "Compare made-up laptop prices" in drafts[0] and "every Monday at 9" in drafts[0]
    assert _nothing_saved(isolated)  # shown, not saved

    listed = client.get("/api/repeat/drafts", headers=H).json()
    assert [x["id"] for x in listed["items"]] == [d["id"]] and listed["ttl_s"] == 3600
    assert listed["min_interval_minutes"] == 30
    opened = client.get(f"/api/repeat/drafts/{d['id']}", headers=H).json()
    assert opened["draft_sha256"] == d["draft_sha256"] and opened["skill_text"] == d["skill_text"]

    r = client.post(f"/api/repeat/drafts/{d['id']}/save", headers=H, json={"draft_sha256": d["draft_sha256"]})
    assert r.status_code == 200, r.text
    saved = r.json()
    [s] = _schedules(isolated)
    assert saved["saved"] is True and saved["schedule_id"] == s.id and saved["skill"] == "weekly-price-check"
    assert (s.kind, s.target, s.cron, s.source) == ("skill", "weekly-price-check", "0 9 * * mon", "repeat")
    assert (isolated / "skills" / "weekly-price-check" / "SKILL.md").exists()
    assert "unattended runs do only T0/T1 actions" in saved["message"]
    assert client.get("/api/repeat/drafts", headers=H).json()["items"] == []
    again = client.post(f"/api/repeat/drafts/{d['id']}/save", headers=H, json={"draft_sha256": d["draft_sha256"]})
    assert again.status_code == 404 and len(_schedules(isolated)) == 1  # answered once only

    events = _events(isolated)
    proposed = next(e for e in events if e["event"] == "automation_proposed")
    assert proposed["channel"] == "dashboard"
    assert next(e for e in events if e["event"] == "automation_saved")["channel"] == "dashboard"
    mine = {e["event"]: e for e in events if e["event"] in ("repeat_proposed", "repeat_saved")}
    assert set(mine["repeat_proposed"]) == {"ts", "event", "source", "proposal", "task_id"}
    assert set(mine["repeat_saved"]) == {"ts", "event", "source", "proposal", "schedule_id"}
    assert mine["repeat_saved"]["schedule_id"] == s.id and mine["repeat_saved"]["source"] == "dashboard"


def test_save_is_bound_to_the_draft_on_screen(client, isolated):
    tid = _task(isolated)
    d = client.post("/api/repeat/propose", headers=H, json={"task_id": tid, "when": "every Monday at 9"}).json()
    r = client.post(f"/api/repeat/drafts/{d['id']}/save", headers=H, json={"draft_sha256": "0" * 64})
    assert r.status_code == 409 and _nothing_saved(isolated)
    # The stored draft changes after it was shown: the old click no longer saves anything.
    path = RepeatStore(isolated / "data").pending_dir / f"{d['id']}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["schedule"]["cron"] = "0 9 * * *"
    path.write_text(json.dumps(data), encoding="utf-8")
    r = client.post(f"/api/repeat/drafts/{d['id']}/save", headers=H, json={"draft_sha256": d["draft_sha256"]})
    assert r.status_code == 409 and _nothing_saved(isolated)
    assert client.post(f"/api/repeat/drafts/{d['id']}/save", headers=H, json={}).status_code == 422
    assert client.post(f"/api/repeat/drafts/{d['id']}/save", headers=H,
                       json={"draft_sha256": "not-a-hash"}).status_code == 422
    refused = [e for e in _events(isolated) if e["event"] == "repeat_save_refused"]
    assert len(refused) == 2 and all(e["reason"] == "draft_changed" for e in refused)


def test_steps_that_need_approval_are_listed(client, isolated, drafts):
    drafts.draft = WITH_APPROVAL_STEPS
    tid = _task(isolated)
    d = client.post("/api/repeat/propose", headers=H, json={"task_id": tid, "when": "every day at 21:00"}).json()
    assert d["held_steps"] == ["3. Replace last week's summary (overwrite_file, T2)",
                               "4. Send the contact form (browser_submit, T3)"]
    assert "These steps need approval, so scheduled runs will NOT do them on their own" in d["show"]


def test_cancel_drops_the_draft(client, isolated):
    tid = _task(isolated)
    d = client.post("/api/repeat/propose", headers=H, json={"task_id": tid, "when": "every Monday at 9"}).json()
    r = client.post(f"/api/repeat/drafts/{d['id']}/cancel", headers=H)
    assert r.status_code == 200 and r.json()["message"] == "Not saved."
    assert client.get("/api/repeat/drafts", headers=H).json()["items"] == []
    assert client.post(f"/api/repeat/drafts/{d['id']}/save", headers=H,
                       json={"draft_sha256": d["draft_sha256"]}).status_code == 404
    assert client.post(f"/api/repeat/drafts/{d['id']}/cancel", headers=H).status_code == 404
    assert _nothing_saved(isolated)
    names = [e["event"] for e in _events(isolated)]
    assert "automation_dropped" in names and "repeat_cancelled" in names


# ---- the rules from repeat.py still apply ----

def test_refusals_come_back_as_clear_errors(client, isolated, drafts):
    tid = _task(isolated)
    failed = _task(isolated, state="FAILED")
    r = client.post("/api/repeat/propose", headers=H, json={"task_id": tid, "when": "every 5 minutes"})
    assert r.status_code == 400 and "at most every 30 minutes" in r.json()["detail"]
    r = client.post("/api/repeat/propose", headers=H, json={"task_id": failed, "when": "every Monday at 9"})
    assert r.status_code == 400 and f"({failed} is FAILED)" in r.json()["detail"]
    r = client.post("/api/repeat/propose", headers=H, json={"task_id": tid, "when": "whenever it feels right"})
    assert r.status_code == 400 and "could not read the time" in r.json()["detail"].lower()
    assert client.post("/api/repeat/propose", headers=H,
                       json={"task_id": "t-999", "when": "every Monday at 9"}).status_code == 404
    assert client.post("/api/repeat/propose", headers=H,
                       json={"task_id": "../x", "when": "every Monday at 9"}).status_code == 422
    assert client.post("/api/repeat/propose", headers=H, json={"task_id": tid, "when": ""}).status_code == 422
    assert drafts == [] and client.get("/api/repeat/drafts", headers=H).json()["items"] == []
    assert _nothing_saved(isolated)


def test_emergency_stop_blocks_drafting(client, isolated, drafts):
    tid = _task(isolated)
    StopSwitch(isolated / "data").engage("test")
    r = client.post("/api/repeat/propose", headers=H, json={"task_id": tid, "when": "every Monday at 9"})
    assert r.status_code == 409 and drafts == []


def test_an_expired_draft_cannot_be_opened_or_saved(client, isolated):
    tid = _task(isolated)
    d = client.post("/api/repeat/propose", headers=H, json={"task_id": tid, "when": "every Monday at 9"}).json()
    path = RepeatStore(isolated / "data").pending_dir / f"{d['id']}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["created_ts"] = time.time() - repeat_mod.PENDING_TTL_S - 5
    path.write_text(json.dumps(data), encoding="utf-8")
    r = client.post(f"/api/repeat/drafts/{d['id']}/save", headers=H,
                    json={"draft_sha256": draft_hash(RepeatProposal(**data))})
    assert r.status_code == 404 and "expired" in r.json()["detail"] and _nothing_saved(isolated)
    assert client.get(f"/api/repeat/drafts/{d['id']}", headers=H).status_code == 404
    assert client.get("/api/repeat/drafts", headers=H).json()["items"] == [] and not path.exists()


def test_ids_are_checked(client):
    assert client.get("/api/repeat/drafts/rp-zzzzzz", headers=H).status_code == 400
    assert client.get("/api/repeat/drafts/rp-000000", headers=H).status_code == 404
    assert client.post("/api/repeat/drafts/x;y/cancel", headers=H).status_code == 400


# ---- drafts made in chat or on Telegram ----

def test_a_draft_from_telegram_or_chat_can_be_opened_and_saved_here(client, isolated):
    tid = _task(isolated)
    rt = open_runtime()
    try:  # what /repeat on Telegram does: propose with channel "telegram"
        tg = repeat_mod.propose(rt, proactive(NOW), "every Monday at 9", task_id=tid, owner_session="tg-chat",
                                channel="telegram")
    finally:
        rt.close()
    chat = RepeatProposal("rp-abc123", "chat demo-session", "Summarize the made-up notes", "every day at 21:00",
                          tg.skill_text.replace("weekly-price-check", "notes-summary"), "notes-summary",
                          {**tg.schedule, "cron": "0 21 * * *", "name": "notes-summary", "target": "notes-summary",
                           "description": "every day at 21:00"}, "demo-session", "2026-10-10T15:00:00", time.time())
    RepeatStore(isolated / "data").put(chat)

    items = {x["id"]: x for x in client.get("/api/repeat/drafts", headers=H).json()["items"]}
    assert set(items) == {tg.id, chat.id} and items[chat.id]["origin"] == "chat"
    assert items[tg.id]["origin"] == "task" and items[chat.id]["cron"] == "0 21 * * *"
    opened = client.get(f"/api/repeat/drafts/{tg.id}", headers=H).json()
    assert opened["skill_text"] == tg.skill_text  # the full draft Telegram never received
    r = client.post(f"/api/repeat/drafts/{tg.id}/save", headers=H, json={"draft_sha256": opened["draft_sha256"]})
    assert r.status_code == 200 and [s.target for s in _schedules(isolated)] == ["weekly-price-check"]
    assert [x["id"] for x in client.get("/api/repeat/drafts", headers=H).json()["items"]] == [chat.id]
    assert client.post(f"/api/repeat/drafts/{chat.id}/cancel", headers=H).status_code == 200
    assert len(_schedules(isolated)) == 1
