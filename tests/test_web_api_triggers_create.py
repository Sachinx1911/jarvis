"""Creating and deleting event triggers from the dashboard: a sentence becomes a draft that is
shown and saved only on confirm; today's refusals (Amazon/Flipkart, folders outside the
allowed roots) come back as clear errors; an email rule's sender and subject never go back to
the browser (P2 until decision #19); deleting needs a confirm step. Offline: rules only, no
model, fake web and Google. All data is made up."""

import json

import pytest

pytest.importorskip("fastapi")

from jarvis.core.runtime import open_runtime  # noqa: E402
from jarvis.proactive.trigger_parse import TriggerDraft  # noqa: E402
from jarvis.proactive.triggers import TriggerStore  # noqa: E402
from tests.test_proactive_support import at, proactive  # noqa: E402
from tests.test_web_api_app import H, _client, audit_text  # noqa: E402

SENDER = "boss@example.com"  # made-up address
SUBJECT = "quarterly-invoice"
NOW = at(2026, 10, 10, 10, 0)
TRIG = {"enabled": True, "default_cooldown_minutes": 10, "max_events_per_fire": 10, "max_backoff_hours": 6,
        "tavily_daily_credits": 15, "file_new": {"every_minutes": 2},
        "email_from": {"every_minutes": 5, "lookback_days": 2}, "calendar_soon": {"every_minutes": 5},
        "web_price": {"every_hours": 6, "min_every_hours": 2, "ignore_below_fraction": 0.3},
        "web_search_new": {"every_hours": 6, "min_every_hours": 1, "max_results": 5}}


class NoWeb:
    """Drafting never touches the web; any call would be a bug."""

    def __getattr__(self, name):
        raise AssertionError(f"web used while drafting: {name}")


def _proactive():
    p = proactive(NOW, triggers=TRIG)
    p.extras.update(web=NoWeb(), tavily_key=lambda: "tvly-test", google_client=lambda: None,
                    connectors_cfg={"gmail": {"header_class": "P2"}, "google": {"calendar_id": "primary"}})
    return p


@pytest.fixture
def cfgdir(tmp_path):
    d = tmp_path / "cfg"
    d.mkdir()
    return d


@pytest.fixture
def client(isolated, cfgdir):
    (isolated / "workspace" / "inbox").mkdir(parents=True)
    with _client(cfgdir, proactive=_proactive) as c:
        yield c


def _triggers():
    rt = open_runtime()
    try:
        return TriggerStore(rt.store.conn).list()
    finally:
        rt.close()


def _events(home) -> list[dict]:
    return [json.loads(line) for line in audit_text(home).splitlines()]


def _draft(client, text, **kw):
    return client.post("/api/triggers/draft", headers=H, json={"text": text, **kw})


# ---- draft, then confirm ----

def test_sentence_is_shown_as_a_draft_and_saved_only_on_confirm(client, isolated):
    r = _draft(client, "when a new file arrives in workspace/inbox tell me")
    assert r.status_code == 200, r.text
    d = r.json()
    assert len(d["draft_id"]) == 24
    assert d["draft"] == {"source": "file_new", "description": "new or changed file in workspace/inbox",
                          "condition": {"folder": "workspace/inbox", "glob": "*"}, "action": "notify", "target": "",
                          "input": "", "output": "telegram", "every_s": 120, "cooldown_s": 600, "read_by": "rules",
                          "private_hidden": False}
    assert "Watches: file_new" in d["show"] and "Checks every 2 min; at most one run per 10 min" in d["show"]
    assert "Runs unattended: only read-only work" in d["show"]
    assert _triggers() == [] and client.get("/api/triggers", headers=H).json()["items"] == []

    r = client.post("/api/triggers/confirm", headers=H, json={"draft_id": d["draft_id"]})
    assert r.status_code == 200, r.text
    assert r.json()["saved"] == {"id": "t-001", "name": "new or changed file in workspace/inbox",
                                 "source": "file_new", "action": "notify", "enabled": True}
    [t] = _triggers()
    assert (t.id, t.created_by, t.every_s) == ("t-001", "dashboard", 120)
    assert client.post("/api/triggers/confirm", headers=H, json={"draft_id": d["draft_id"]}).status_code == 404
    assert len(_triggers()) == 1

    events = {e["event"]: e for e in _events(isolated)}
    assert set(events["trigger_drafted"]) == {"ts", "event", "source", "source_kind", "action"}
    assert events["trigger_added"]["trigger_id"] == "t-001" and events["trigger_added"]["created_by"] == "dashboard"


def test_options_output_interval_cooldown_and_action(client):
    d = _draft(client, "when a new file arrives in workspace/inbox summarize it", output="file", every_minutes=10,
               cooldown_minutes=0).json()["draft"]
    assert (d["action"], d["input"], d["output"], d["every_s"], d["cooldown_s"]) == (
        "prompt", "summarize it", "file", 600, 0)
    d = _draft(client, "tell me when there are new results for 'made-up gadget launch'", every_minutes=5).json()
    assert d["draft"]["source"] == "web_search_new" and d["draft"]["every_s"] == 3600  # web checks: at most hourly
    assert "Uses Tavily credits" in d["show"]
    d = _draft(client, "when a new file arrives in workspace/inbox", kind="skill", target="notes-summary").json()
    assert (d["draft"]["action"], d["draft"]["target"]) == ("skill", "notes-summary")
    r = _draft(client, "when a new file arrives in workspace/inbox", kind="skill")
    assert r.status_code == 400 and "needs a skill name" in r.json()["detail"]
    assert _draft(client, "x", output="sms").status_code == 422
    assert _draft(client, "x", every_minutes=0.5).status_code == 422
    assert _triggers() == []


def test_discarded_draft_cannot_be_confirmed(client, isolated):
    d = _draft(client, "when a new file arrives in workspace/inbox tell me").json()
    assert client.post("/api/triggers/discard", headers=H, json={"draft_id": d["draft_id"]}).json() == {
        "discarded": True}
    assert client.post("/api/triggers/confirm", headers=H, json={"draft_id": d["draft_id"]}).status_code == 404
    assert _triggers() == [] and "trigger_draft_discarded" in audit_text(isolated)


def test_schedule_and_trigger_drafts_cannot_be_swapped(client):
    s = client.post("/api/schedules/draft", headers=H, json={"text": "every day at 9 hello", "use_model": False}).json()
    t = _draft(client, "when a new file arrives in workspace/inbox tell me").json()
    assert client.post("/api/triggers/confirm", headers=H, json={"draft_id": s["draft_id"]}).status_code == 404
    assert client.post("/api/schedules/confirm", headers=H, json={"draft_id": t["draft_id"]}).status_code == 404
    assert _triggers() == []


# ---- questions and refusals ----

@pytest.mark.parametrize("url", ["https://www.amazon.in/dp/B0TEST1234", "https://www.flipkart.com/x/p/itm123"])
def test_amazon_and_flipkart_are_refused_with_the_reason(client, isolated, url):
    r = _draft(client, f"tell me when the price of the made-up laptop drops below 75000 {url}")
    assert r.status_code == 400 and "terms forbid" in r.json()["detail"]
    assert r.json()["detail"].startswith("Not saved:") and "Not saved: Not saved" not in r.json()["detail"]
    assert _triggers() == [] and "trigger_draft_refused" in audit_text(isolated)


def test_folder_outside_the_allowed_roots_is_refused(client):
    r = _draft(client, "when a new file arrives in /etc tell me")
    assert r.status_code == 400 and "outside the folders Jarvis may read" in r.json()["detail"]
    r = _draft(client, "when a new file arrives in ../../outside tell me")
    assert r.status_code == 400 and "outside the folders" in r.json()["detail"]
    assert _triggers() == []


def test_unclear_text_gets_a_question(client):
    r = _draft(client, "hello there")
    assert r.status_code == 200 and r.json()["draft_id"] is None and "could not tell" in r.json()["question"]
    r = _draft(client, "when a new file arrives tell me")
    assert r.json()["draft_id"] is None and "Which folder" in r.json()["question"]
    assert _draft(client, "   ").status_code == 400
    assert _triggers() == []


# ---- email rules keep the sender private ----

def test_email_trigger_draft_hides_sender_and_subject(client, isolated):
    r = _draft(client, f"when I get an email from {SENDER} with subject {SUBJECT} tell me")
    assert r.status_code == 200, r.text
    d = r.json()
    assert SENDER not in r.text and SUBJECT not in r.text
    assert d["draft"]["source"] == "email_from" and d["draft"]["private_hidden"] is True
    assert d["draft"]["condition"] == {"sender": "[hidden: P2]", "subject": "[hidden: P2]"}
    assert "Watches: email_from" in d["show"] and "the email text itself is never passed on" in d["show"]
    r = client.post("/api/triggers/confirm", headers=H, json={"draft_id": d["draft_id"]})
    assert r.status_code == 200 and SENDER not in r.text and r.json()["saved"]["name"] == "email rule t-001"
    [t] = _triggers()
    assert t.condition["sender"] == SENDER  # saved as typed; only the browser never sees it again
    listing = client.get("/api/triggers", headers=H)
    assert SENDER not in listing.text and SUBJECT not in listing.text
    assert SENDER not in audit_text(isolated) and SUBJECT not in audit_text(isolated)


# ---- delete with a confirm step ----

def _add(name="new file in inbox") -> str:
    rt = open_runtime()
    try:
        return TriggerStore(rt.store.conn).add(TriggerDraft(
            name=name, source="file_new", condition={"folder": "workspace/inbox", "glob": "*"}, action="notify",
            output="file", description=name), NOW.replace(tzinfo=None), "cli").id
    finally:
        rt.close()


def test_delete_needs_the_confirm_step(client, isolated):
    tid = _add()
    assert client.post(f"/api/triggers/{tid}/delete", headers=H).status_code == 422          # no confirmation
    r = client.post(f"/api/triggers/{tid}/delete", headers=H, json={"confirm": "t-002"})      # another id
    assert r.status_code == 409 and len(_triggers()) == 1
    r = client.post(f"/api/triggers/{tid}/delete", headers=H, json={"confirm": tid})
    # law 2: the dashboard archives; the row stays, hidden from the list
    assert r.status_code == 200 and r.json() == {"id": tid, "deleted": False, "archived": True} and _triggers() == []
    assert client.post(f"/api/triggers/{tid}/delete", headers=H, json={"confirm": tid}).status_code == 409
    assert client.post("/api/triggers/bad;id/delete", headers=H, json={"confirm": "bad;id"}).status_code == 400
    [e] = [e for e in _events(isolated) if e["event"] == "trigger_archive"]
    assert set(e) == {"ts", "event", "trigger_id", "source"} and e["source"] == "dashboard"


# ---- token and origin ----

def test_new_trigger_routes_need_token_and_own_origin(client):
    tid = _add()
    for path, body in [("/api/triggers/draft", {"text": "when a new file arrives in workspace/inbox tell me"}),
                       ("/api/triggers/confirm", {"draft_id": "0" * 24}),
                       ("/api/triggers/discard", {"draft_id": "0" * 24}),
                       (f"/api/triggers/{tid}/delete", {"confirm": tid})]:
        assert client.post(path, json=body).status_code == 401, path
        assert client.post(path, json=body, headers={**H, "Origin": "https://evil.example"}).status_code == 403, path
        assert client.post(path, json=body, headers={**H, "Sec-Fetch-Site": "cross-site"}).status_code == 403, path
        assert client.post(path, json=body, headers={**H, "Host": "evil.example"}).status_code == 400, path
    d = _draft(client, "when a new file arrives in workspace/inbox tell me").json()
    r = client.post("/api/triggers/confirm", headers={**H, "Origin": "https://evil.example"},
                    json={"draft_id": d["draft_id"]})
    assert r.status_code == 403 and [t.id for t in _triggers()] == [tid]
