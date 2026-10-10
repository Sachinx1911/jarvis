"""Dashboard trust API: memory sources, trash/restore, sensitivity filter, "why did Jarvis
say that", standing approvals and approval previews. Offline: fake provider only."""

import threading

import pytest

pytest.importorskip("fastapi")

from jarvis.core.runtime import open_runtime  # noqa: E402
from jarvis.memory.model import Memory  # noqa: E402
from jarvis.paths import PROMPTS_DIR  # noqa: E402
from tests.test_web_api import H, Scripted, _client, _wait_pending  # noqa: E402


def _save(**kw) -> str:
    rt = open_runtime()
    try:
        kw.setdefault("evidence", kw["name"])
        return rt.memory.save(Memory(**kw)).id
    finally:
        rt.close()


def _chat_line(session_id: str, text: str) -> int:
    from jarvis.providers.base import Message

    rt = open_runtime()
    try:
        return rt.store.add_message(session_id, Message.text("user", text))
    finally:
        rt.close()


def test_source_shows_quote_chat_method_and_chain(isolated):
    mid_line = _chat_line("s-past1", "my garden shed key is in the blue drawer")
    old = _save(name="shed key place", evidence="shed key is in the red box")
    new = _save(name="shed key drawer", evidence="garden shed key is in the blue drawer", keywords="shed key drawer")
    rt = open_runtime()
    try:
        o = rt.memory.get(old)
        o.status, o.superseded_by = "superseded", new
        rt.memory.update(o)
        rt.audit.write("memory_saved", id=new, type="fact", how="extract:SUPERSEDE")
    finally:
        rt.close()
    with _client() as c:
        s = c.get(f"/api/memory/{new}/source", headers=H).json()
        assert s["evidence"] == "garden shed key is in the blue drawer"
        assert s["method"] == "extract" and s["saved_at"]
        assert s["sessions"][0]["session_id"] == "s-past1" and s["sessions"][0]["message_id"] == mid_line
        assert "blue drawer" in s["sessions"][0]["excerpt"]
        assert [x["id"] for x in s["chain"]] == [old] and s["newer"] is None
        assert c.get(f"/api/memory/{old}/source", headers=H).json()["newer"] == new
        lines = c.get(f"/api/sessions/s-past1/messages?around={mid_line}", headers=H).json()["items"]
        assert lines[0]["id"] == mid_line and "blue drawer" in lines[0]["text"]
        assert c.get("/api/memory/bad-id/source", headers=H).status_code == 400


def test_interview_and_remember_methods(isolated):
    q = next(l[2:].strip() for l in (PROMPTS_DIR / "interview.md").read_text(encoding="utf-8").splitlines()
             if l.startswith("- "))
    a = _save(name="answer", evidence=f"{q} short answer")
    b = _save(name="told", evidence="remember that the gate code changes monthly")
    rt = open_runtime()
    try:
        rt.audit.write("memory_saved", id=b, type="fact", how="remember")
    finally:
        rt.close()
    with _client() as c:
        assert c.get(f"/api/memory/{a}/source", headers=H).json()["method"] == "interview"
        assert c.get(f"/api/memory/{b}/source", headers=H).json()["method"] == "remember"


def test_sensitive_source_masked_until_revealed(isolated):
    _chat_line("s-x", "my blood pressure medicine is taken at 9 pm")
    mid = _save(name="bp medicine time", evidence="blood pressure medicine is taken at 9 pm", sensitivity="sensitive")
    with _client() as c:
        s = c.get(f"/api/memory/{mid}/source", headers=H).json()
        assert s["masked"] and s["evidence"] == "" and all(x["excerpt"] == "" for x in s["sessions"])
        lines = c.get("/api/sessions/s-x/messages", headers=H).json()["items"]
        assert lines[0]["masked"] and "pressure" not in lines[0]["text"]
        r = c.get(f"/api/memory/{mid}/source?reveal=true", headers=H).json()
        assert "blood pressure" in r["evidence"]


def test_sensitivity_filter(isolated):
    _save(name="likes tea")
    _save(name="voting view", sensitivity="sensitive")
    with _client() as c:
        assert len(c.get("/api/memory", headers=H).json()["items"]) == 2
        sens = c.get("/api/memory?sensitivity=sensitive", headers=H).json()["items"]
        assert len(sens) == 1 and sens[0]["masked"]
        assert [m["name"] for m in c.get("/api/memory?sensitivity=normal", headers=H).json()["items"]] == ["likes tea"]


def test_trash_needs_confirm_and_restores(isolated):
    mid = _save(name="old phone model", keywords="phone")
    with _client() as c:
        assert c.post(f"/api/memory/{mid}/trash", headers=H, json={}).status_code == 400
        assert c.get(f"/api/memory/{mid}", headers=H).status_code == 200
        r = c.post(f"/api/memory/{mid}/trash", headers=H, json={"confirm": True}).json()
        assert r["trashed"]["id"] == mid
        assert c.get(f"/api/memory/{mid}", headers=H).status_code == 404
        assert (isolated / "memory" / ".trash" / r["trashed"]["file"]).exists()  # never hard-deleted
        items = c.get("/api/memory-trash", headers=H).json()["items"]
        assert items[0]["id"] == mid and items[0]["trashed_at"]
        back = c.post(f"/api/memory-trash/{r['trashed']['file']}/restore", headers=H).json()
        assert back["id"] == mid and c.get(f"/api/memory/{mid}", headers=H).status_code == 200


def test_archive_then_activate(isolated):
    mid = _save(name="gym days")
    with _client() as c:
        assert c.post(f"/api/memory/{mid}/activate", headers=H).status_code == 409
        c.post(f"/api/memory/{mid}/archive", headers=H)
        assert c.post(f"/api/memory/{mid}/activate", headers=H).json()["status"] == "active"


def test_why_did_jarvis_say_that(isolated):
    mid = _save(name="garden shed key", keywords="garden shed key drawer", summary_en="The shed key is in the drawer.")
    with _client(factory=Scripted(["It is in the drawer, sir."])) as c:
        sid = c.post("/api/chat/sessions", headers=H).json()["id"]
        r = c.post(f"/api/chat/sessions/{sid}/messages", headers=H, json={"text": "where is the garden shed key?"}).json()
        assert r["turn_id"]
        why = c.get(f"/api/chat/turns/{r['turn_id']}", headers=H).json()
        assert mid in [m["id"] for m in why["memories"]]
        assert c.get("/api/chat/turns/999", headers=H).status_code == 404
        cmd = c.post(f"/api/chat/sessions/{sid}/messages", headers=H, json={"text": "/help"}).json()
        assert cmd.get("turn_id") is None


def test_grants_api(isolated):
    (isolated / "workspace" / "notes").mkdir(parents=True, exist_ok=True)
    with _client() as c:
        g = c.get("/api/grants", headers=H).json()
        names = {t["name"]: t["tier"] for t in g["tools"]}
        assert "write_file" in names and "delete_file" not in names and "gmail_send" not in names
        bad = c.post("/api/grants", headers=H, json={"tool": "delete_file", "constraints": {"path": {"glob": "*"}}})
        assert bad.status_code == 400
        bad = c.post("/api/grants", headers=H, json={"tool": "write_file", "constraints": {"path": {"any": True}}})
        assert bad.status_code == 400 and "exact rule" in bad.json()["detail"]
        made = c.post("/api/grants", headers=H, json={
            "tool": "write_file", "constraints": {"path": {"glob": "notes/*.md"}, "content": {"max_chars": 200}},
            "days": 3, "max_uses": 5, "note": "daily notes"}).json()
        assert made["active"] and made["created_by"] == "dashboard"
        assert c.get("/api/grants", headers=H).json()["items"][0]["id"] == made["id"]
        assert c.get(f"/api/grants/{made['id']}/uses", headers=H).json()["items"] == []
        rev = c.post(f"/api/grants/{made['id']}/revoke", headers=H).json()
        assert rev["revoked"] and not rev["active"]
        assert c.post("/api/grants/g-00000000/revoke", headers=H).status_code == 404


def test_pending_approval_carries_preview(isolated):
    (isolated / "workspace").mkdir(exist_ok=True)
    (isolated / "workspace" / "note.txt").write_text("old line", encoding="utf-8")
    script = [{"tool": "overwrite_file", "arguments": {"path": "note.txt", "content": "new line"}}, "Done."]
    with _client(factory=Scripted(script)) as c:
        sid = c.post("/api/chat/sessions", headers=H).json()["id"]
        t = threading.Thread(target=lambda: c.post(f"/api/chat/sessions/{sid}/messages", headers=H,
                                                   json={"text": "change it"}))
        t.start()
        p = _wait_pending(c)[0]
        assert "- old line" in p["preview"] and "+ new line" in p["preview"]
        assert p["scope"] == "" and "WHAT WILL HAPPEN" in p["describe"]
        c.post(f"/api/approvals/{p['id']}", headers=H, json={"decision": "deny"})
        t.join(10)


def test_prompts_mark_health_and_politics_sensitive():
    for name in ("memory_enrich.md", "memory_extract.md"):
        text = (PROMPTS_DIR / name).read_text(encoding="utf-8")
        line = next(l for l in text.splitlines() if 'sensitivity: "sensitive"' in l)
        assert "health" in line and "political opinions" in line
        assert "family members' names" in line  # the P1 list is unchanged
