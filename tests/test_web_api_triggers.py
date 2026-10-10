"""Event triggers in the dashboard: the read-only list from the trigger engine's own hook
(adapters.HOOKS "triggers"), pause/resume and the runs (fires) of one trigger.
Offline, synthetic triggers only."""

from datetime import datetime

import pytest

pytest.importorskip("fastapi")

from jarvis.core.runtime import open_runtime  # noqa: E402
from jarvis.proactive.trigger_parse import TriggerDraft  # noqa: E402
from jarvis.proactive.triggers import TriggerStore  # noqa: E402
from jarvis.web import adapters  # noqa: E402
from tests.test_web_api_app import H, _client, audit_text  # noqa: E402

SENDER = "boss@example.com"  # made-up address
NOW = datetime(2026, 10, 10, 9, 0)


@pytest.fixture
def cfgdir(tmp_path):
    d = tmp_path / "cfg"
    d.mkdir()
    return d


@pytest.fixture
def client(isolated, cfgdir):
    with _client(cfgdir) as c:
        yield c


def _add_triggers() -> tuple[str, str]:
    rt = open_runtime()
    try:
        store = TriggerStore(rt.store.conn)
        f = store.add(TriggerDraft(name="new file in inbox", source="file_new",
                                   condition={"folder": "workspace/inbox", "pattern": "*"}, action="notify",
                                   output="file", description="new file in workspace/inbox"), NOW, "cli")
        e = store.add(TriggerDraft(name=f"email from {SENDER}", source="email_from", condition={"sender": SENDER},
                                   action="prompt", input="summarize it", description=f"email from {SENDER}"),
                      NOW, "cli")
        fid = store.start_fire(f.id, 1, NOW)
        store.finish_fire(fid, "ok", "- inbox/plan.txt arrived", NOW, None, 0, 0)
        store.update_poll(f.id, NOW, "fired", "1 event(s)", NOW, failures=0, fired=True)
        eid = store.start_fire(e.id, 1, NOW)
        store.finish_fire(eid, "ok", f"- new mail from {SENDER}: quarterly numbers", NOW, None, 0, 1)
        return f.id, e.id
    finally:
        rt.close()


def test_triggers_hook_is_wired():
    assert adapters.HOOKS["triggers"] == ("jarvis.proactive.triggers", "dashboard_triggers")


def test_triggers_list_status_and_last_fire(client):
    assert client.get("/api/triggers", headers=H).json()["items"] == []
    fid, eid = _add_triggers()
    r = client.get("/api/triggers", headers=H)
    data = r.json()
    assert data["installed"] is True and data["wired"] is True and data["running_here"] is False
    items = {t["id"]: t for t in data["items"]}
    assert items[fid]["enabled"] is True and items[fid]["last_status"] == "fired" and items[fid]["last_fired"]
    assert items[fid]["source"] == "file_new" and items[fid]["what"] == "new file in workspace/inbox"
    # An email rule's sender is P2 until decision #19: not in the list.
    assert items[eid]["what"] == "new email matching a rule" and SENDER not in r.text
    assert client.get("/api/settings", headers=H).json()["modules"]["triggers"] is True


def test_trigger_pause_resume_audited(client, isolated):
    fid, _ = _add_triggers()
    r = client.post(f"/api/triggers/{fid}/pause", headers=H)
    assert r.status_code == 200 and r.json() == {"id": fid, "done": "pause", "enabled": False}
    items = {t["id"]: t for t in client.get("/api/triggers", headers=H).json()["items"]}
    assert items[fid]["enabled"] is False and items[fid]["next_check"] is None
    assert client.post(f"/api/triggers/{fid}/resume", headers=H).json()["enabled"] is True
    log = audit_text(isolated)
    assert '"trigger_pause"' in log and '"trigger_resume"' in log and '"source": "dashboard"' in log


def test_trigger_runs_hide_email_details(client):
    fid, eid = _add_triggers()
    runs = client.get(f"/api/triggers/{fid}/runs", headers=H).json()["runs"]
    assert runs[0]["status"] == "ok" and "plan.txt" in runs[0]["detail"]
    r = client.get(f"/api/triggers/{eid}/runs", headers=H)
    assert r.json()["runs"][0]["detail"] is None and r.json()["runs"][0]["model_calls"] == 1
    assert SENDER not in r.text and r.json()["safe_name"] == f"email rule {eid}"


def test_trigger_routes_check_ids_and_actions(client):
    _add_triggers()
    assert client.post("/api/triggers/t-999/pause", headers=H).status_code == 404
    assert client.post("/api/triggers/bad;id/pause", headers=H).status_code == 400
    assert client.get("/api/triggers/x/runs", headers=H).status_code == 400
    assert client.post("/api/triggers/t-001/delete", headers=H).status_code == 422  # delete needs the confirm body with the trigger id


def test_trigger_routes_need_token_and_own_origin(client):
    fid, _ = _add_triggers()
    assert client.get("/api/triggers").status_code == 401
    assert client.post(f"/api/triggers/{fid}/pause").status_code == 401
    assert client.get(f"/api/triggers/{fid}/runs").status_code == 401
    r = client.post(f"/api/triggers/{fid}/pause", headers={**H, "Origin": "https://evil.example"})
    assert r.status_code == 403
    r = client.post(f"/api/triggers/{fid}/pause", headers={**H, "Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403
    items = {t["id"]: t for t in client.get("/api/triggers", headers=H).json()["items"]}
    assert items[fid]["enabled"] is True
