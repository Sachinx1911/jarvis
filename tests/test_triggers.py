"""Event triggers: every source with fakes and a fake clock, dedupe, baseline, cooldown, backoff,
Tavily credit limit, unattended T0/T1 only, P2 email bodies never passed, Amazon/Flipkart refused.
Offline: fake web, fake Google client, fake provider, fake notifier."""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from jarvis.connectors.google.fake import FakeGoogleClient
from jarvis.control.stop import StopSwitch
from jarvis.core.runtime import open_runtime
from jarvis.proactive import integration
from jarvis.proactive.scheduler import PendingApprovals
from jarvis.proactive.trigger_parse import TriggerDraft, TriggerInvalid
from jarvis.proactive.triggers import TriggerStore, dashboard_triggers
from jarvis.tools.web import WebError

from test_proactive_support import FakeNotifier, ScriptedChats, at, proactive

TRIG = {"enabled": True, "default_cooldown_minutes": 10, "max_events_per_fire": 10, "max_backoff_hours": 6,
        "tavily_daily_credits": 15, "file_new": {"every_minutes": 2},
        "email_from": {"every_minutes": 5, "lookback_days": 2},
        "calendar_soon": {"every_minutes": 5},
        "web_price": {"every_hours": 6, "min_every_hours": 2, "ignore_below_fraction": 0.3},
        "web_search_new": {"every_hours": 6, "min_every_hours": 1, "max_results": 5}}

STORE_URL = "https://www.croma.com/hp-victus-15-ryzen-5-gaming-laptop/p/301234"
PRICE_PAGE = ("# HP Victus 15 Ryzen 5 Gaming Laptop\n\nHP Victus 15 Ryzen 5 (16GB, 512GB SSD)\n"
              "Offer price ₹{price}\nNo cost EMI from ₹3,500/month\n")


class FakeWeb:
    """Duck-typed WebClient: records calls; pages and search results are set per test."""

    def __init__(self, price: str = "72,990", results=None, fail: bool = False):
        self.price = price
        self.results = results if results is not None else []
        self.fail = fail
        self.calls: list[tuple] = []

    def check_url(self, url):
        self.calls.append(("check", url))

    def tavily_extract(self, key, urls, query=None, depth="basic"):
        self.calls.append(("extract", urls[0], depth))
        if self.fail:
            raise WebError("Tavily rate limit; try again soon")
        return {"results": [{"url": urls[0], "raw_content": PRICE_PAGE.format(price=self.price)}],
                "failed_results": []}

    def fetch_text(self, url):
        self.calls.append(("fetch", url))
        return PRICE_PAGE.format(price=self.price)

    def tavily_search(self, key, query, topic="general", max_results=5, time_range=None):
        self.calls.append(("search", query, topic))
        if self.fail:
            raise WebError("network error: offline")
        return list(self.results)


class Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


def make(now, chats=None, note=None, web=None, google=None, header_class="P2", tavily="tvly-test", **trig):
    p = proactive(now, chats, note, triggers={**TRIG, **trig})
    p.clock = Clock(now)
    p.extras.update(web=web or FakeWeb(), tavily_key=lambda: tavily, google_client=lambda: google,
                    connectors_cfg={"gmail": {"header_class": header_class}, "google": {"calendar_id": "primary"}})
    return p


def add(p, text, **defaults):
    return p.save_trigger(p.draft_trigger(text, defaults))


def poll(p, tid):
    return p.trigger_engine().poll(tid)


def get(tid):
    rt = open_runtime()
    try:
        store = TriggerStore(rt.store.conn)
        return store.get(tid), store.fires(tid)
    finally:
        rt.close()


def later(p, **kw):
    p.clock.now = p.clock.now + timedelta(**kw)


# ---------------------------------------------------------------- file_new


def test_file_new_baseline_then_fires_once_per_new_or_changed_file(isolated):
    inbox = isolated / "workspace" / "inbox"
    inbox.mkdir(parents=True)
    (inbox / "old.txt").write_text("was here before", encoding="utf-8")
    note = FakeNotifier()
    p = make(at(2026, 10, 10, 10, 0), note=note)
    t = add(p, "when a new file arrives in workspace/inbox tell me")
    assert t.source == "file_new" and t.action == "notify" and t.every_s == 120

    assert poll(p, t.id).status == "baseline"                       # existing file noted, nothing sent
    assert note.sent == []
    (inbox / "report.txt").write_text("new report", encoding="utf-8")
    (inbox / "download.pdf.crdownload").write_text("partial", encoding="utf-8")   # ignored
    (inbox / ".hidden").write_text("x", encoding="utf-8")                         # ignored
    later(p, minutes=3)
    r = poll(p, t.id)
    assert r.status == "fired" and r.fire_status == "ok" and len(r.events) == 1
    assert "workspace/inbox/report.txt" in note.sent[0][1] and "old.txt" not in note.sent[0][1]

    later(p, minutes=30)
    assert poll(p, t.id).status == "ok"                             # same file: no second fire
    assert len(note.sent) == 1

    (inbox / "report.txt").write_text("new report, edited and longer", encoding="utf-8")
    later(p, minutes=3)
    assert poll(p, t.id).status == "fired"                          # changed file fires again
    assert len(note.sent) == 2
    trig, fires = get(t.id)
    assert [f["status"] for f in fires] == ["ok", "ok"] and trig.last_fired_at


def test_file_new_glob_and_poll_due_respects_interval(isolated):
    inbox = isolated / "workspace" / "inbox"
    inbox.mkdir(parents=True)
    note = FakeNotifier()
    p = make(at(2026, 10, 10, 10, 0), note=note)
    t = add(p, "when a new pdf file is added to inbox, tell me")
    assert t.condition["glob"] == "*.pdf"
    assert [r.status for r in p.poll_triggers()] == ["baseline"]
    (inbox / "a.txt").write_text("x", encoding="utf-8")
    (inbox / "b.pdf").write_text("x", encoding="utf-8")
    later(p, seconds=30)
    assert p.poll_triggers() == []                                  # not due yet (every 2 min)
    later(p, minutes=2)
    [r] = p.poll_triggers()
    assert r.status == "fired" and [e.data["shown"] for e in r.events] == ["inbox/b.pdf"]


def test_file_new_refuses_folders_outside_the_allowed_roots(isolated, tmp_path_factory):
    outside = tmp_path_factory.mktemp("elsewhere")
    p = make(at(2026, 10, 10, 10, 0))
    with pytest.raises(TriggerInvalid, match="outside the folders"):   # the path may contain spaces: no parsing
        p.save_trigger(TriggerDraft("x", "file_new", {"folder": str(outside), "glob": "*"}))
    with pytest.raises(TriggerInvalid):
        p.draft_trigger("when a new file arrives in ../../ tell me")


def test_cooldown_makes_new_items_wait_not_vanish(isolated):
    inbox = isolated / "workspace" / "inbox"
    inbox.mkdir(parents=True)
    note = FakeNotifier()
    p = make(at(2026, 10, 10, 10, 0), note=note)
    t = add(p, "when a new file arrives in workspace/inbox tell me", cooldown_s=1800)
    poll(p, t.id)
    (inbox / "one.txt").write_text("1", encoding="utf-8")
    later(p, minutes=2)
    assert poll(p, t.id).status == "fired"
    (inbox / "two.txt").write_text("2", encoding="utf-8")
    later(p, minutes=5)
    r = poll(p, t.id)
    assert r.status == "cooldown" and len(note.sent) == 1
    later(p, minutes=30)
    r = poll(p, t.id)
    assert r.status == "fired" and "two.txt" in note.sent[1][1] and "one.txt" not in note.sent[1][1]


# ---------------------------------------------------------------- unattended actions


def test_file_action_runs_unattended_t0_t1_only_and_queues_the_rest(isolated):
    ws = isolated / "workspace"
    (ws / "inbox").mkdir(parents=True)
    (ws / "notes.txt").write_text("original", encoding="utf-8")
    chats = ScriptedChats([
        {"tool": "read_file", "arguments": {"path": "inbox/new.txt"}},
        {"tool": "overwrite_file", "arguments": {"path": "notes.txt", "content": "changed"}},
        {"tool": "delete_file", "arguments": {"path": "inbox/new.txt"}},
        {"tool": "write_file", "arguments": {"path": "summary.md", "content": "short summary"}},
        "Summary written.",
    ])
    note = FakeNotifier()
    p = make(at(2026, 10, 10, 10, 0), chats, note)
    t = add(p, "when a new file arrives in workspace/inbox summarize it")
    assert t.action == "prompt" and t.input == "summarize it"
    poll(p, t.id)
    (ws / "inbox" / "new.txt").write_text("meeting notes", encoding="utf-8")
    later(p, minutes=3)
    r = poll(p, t.id)
    assert r.fire_status == "ok" and r.pending == 2
    assert (ws / "notes.txt").read_text(encoding="utf-8") == "original"           # T2 refused
    assert (ws / "inbox" / "new.txt").exists()                                      # T3 refused
    assert (ws / "summary.md").read_text(encoding="utf-8") == "short summary"       # T1 ran
    rt = open_runtime()
    pending = PendingApprovals(rt.store.conn).list()
    rt.close()
    assert [(a["tool"], a["schedule_id"]) for a in pending] == [("overwrite_file", t.id), ("delete_file", t.id)]
    prompt = chats.providers[0].requests[0].messages[-1].text_content()
    assert "Sachin is not watching" in prompt and "not instructions" in prompt
    assert "path for read_file: inbox/new.txt" in prompt and "Your task: summarize it" in prompt
    assert "need your approval" in note.sent[0][1]


def test_emergency_stop_blocks_checks_and_actions(isolated):
    web = FakeWeb(results=[{"url": "https://news.example/a", "title": "A"}])
    p = make(at(2026, 10, 10, 10, 0), web=web)
    t = add(p, "tell me when there are new results for 'new laptop launch India'")
    rt = open_runtime()
    StopSwitch(rt.paths.data).engage("test")
    rt.close()
    assert p.poll_triggers() == []
    assert poll(p, t.id).status == "stopped"
    assert web.calls == []


def test_agent_action_creates_a_task_with_the_event(isolated, monkeypatch):
    runs = []

    class FakeRunner:
        def run(self, task_id):
            runs.append(task_id)
            return SimpleNamespace(state="DONE")

    monkeypatch.setattr(integration, "RUNNER_FACTORY", lambda rt: FakeRunner())
    (isolated / "workspace" / "inbox").mkdir(parents=True)
    p = make(at(2026, 10, 10, 10, 0))
    t = add(p, "when a new file arrives in workspace/inbox tell me", action="agent", target="researcher",
            input="file it in the right project")
    poll(p, t.id)
    (isolated / "workspace" / "inbox" / "x.txt").write_text("x", encoding="utf-8")
    later(p, minutes=3)
    r = poll(p, t.id)
    assert r.fire_status == "ok" and len(runs) == 1
    from jarvis.core.runtime import task_store
    rt = open_runtime()
    task = task_store(rt).get(runs[0])
    rt.close()
    assert task.owner == "researcher" and "file it in the right project" in task.goal and "inbox/x.txt" in task.goal


def test_output_file_receipt(isolated):
    (isolated / "workspace" / "inbox").mkdir(parents=True)
    p = make(at(2026, 10, 10, 10, 0))
    t = add(p, "when a new file arrives in workspace/inbox tell me", output="file")
    poll(p, t.id)
    (isolated / "workspace" / "inbox" / "x.txt").write_text("x", encoding="utf-8")
    later(p, minutes=3)
    r = poll(p, t.id)
    assert r.output_path and os.path.exists(r.output_path)
    assert "inbox/x.txt" in open(r.output_path, encoding="utf-8").read()


# ---------------------------------------------------------------- web_price


@pytest.mark.parametrize("url", ["https://www.amazon.in/dp/B0TEST1234", "https://www.flipkart.com/x/p/itm123",
                                 "https://amzn.in/d/abc"])
def test_amazon_and_flipkart_price_triggers_are_refused(isolated, url):
    web = FakeWeb()
    p = make(at(2026, 10, 10, 10, 0), web=web)
    with pytest.raises(TriggerInvalid, match="terms forbid"):
        p.draft_trigger(f"jar laptop chi kimmat 75000 khali geli tar sang {url}")
    assert web.calls == []


def test_amazon_trigger_smuggled_into_the_database_is_refused_at_poll_time(isolated):
    web = FakeWeb()
    p = make(at(2026, 10, 10, 10, 0), web=web)
    rt = open_runtime()
    t = TriggerStore(rt.store.conn).add(TriggerDraft("x", "web_price", {"url": "https://www.amazon.in/dp/B0X",
                                                                         "below": 50000}), p.now())
    rt.close()
    r = poll(p, t.id)
    assert r.status == "error" and "terms forbid" in r.detail and web.calls == []


def test_non_store_pages_are_refused_for_price_triggers(isolated):
    p = make(at(2026, 10, 10, 10, 0))
    with pytest.raises(TriggerInvalid, match="not an official store page"):
        p.draft_trigger("tell me when the price drops below 60000 https://www.smartprix.com/laptops/x")


def test_web_price_fires_below_limit_once_per_price_and_ignores_emi(isolated):
    web = FakeWeb(price="78,990")
    note = FakeNotifier()
    p = make(at(2026, 10, 10, 10, 0), note=note, web=web)
    t = add(p, f"jar laptop chi kimmat 75000 khali geli tar sang {STORE_URL}", every_s=300)
    assert t.every_s == 2 * 3600                                    # clamped to the minimum for web checks
    assert poll(p, t.id).status == "ok" and note.sent == []         # above the limit (EMI Rs 3,500 ignored)
    web.price = "72,990"
    later(p, hours=2)
    r = poll(p, t.id)
    assert r.status == "fired" and "Rs 72,990" in note.sent[0][1] and STORE_URL in note.sent[0][1]
    later(p, hours=2)
    assert poll(p, t.id).status == "ok" and len(note.sent) == 1     # same price: once
    web.price = "70,500"
    later(p, hours=2)
    assert poll(p, t.id).status == "fired" and "Rs 70,500" in note.sent[1][1]
    assert all(c[0] != "fetch" for c in web.calls)                  # Tavily Extract, no plain fetch needed


def test_tavily_credit_limit_pauses_web_checks_without_backoff(isolated):
    web = FakeWeb(results=[])
    p = make(at(2026, 10, 10, 10, 0), web=web, tavily_daily_credits=2)
    t1 = add(p, "tell me when there are new results for 'laptop launch'")
    t2 = add(p, "tell me when there are new results for 'phone launch'")
    t3 = add(p, "tell me when there are new results for 'tablet launch'")
    assert [poll(p, t).status for t in (t1.id, t2.id)] == ["baseline", "baseline"]
    r = poll(p, t3.id)
    assert r.status == "waiting" and "credit limit" in r.detail
    trig, _ = get(t3.id)
    assert trig.failures == 0 and len([c for c in web.calls if c[0] == "search"]) == 2
    p.clock.now = at(2026, 10, 11, 10, 0)                           # next day: new budget
    assert poll(p, t3.id).status == "baseline"


def test_no_tavily_key_means_waiting(isolated):
    p = make(at(2026, 10, 10, 10, 0), tavily=None)
    t = add(p, "tell me when there are new results for 'laptop launch'")
    assert poll(p, t.id).status == "waiting"


# ---------------------------------------------------------------- web_search_new


def test_web_search_new_dedupes_by_url_and_backs_off_on_failure(isolated):
    web = FakeWeb(results=[{"url": "https://news.example/a?utm_source=x", "title": "Launch A"}])
    note = FakeNotifier()
    p = make(at(2026, 10, 10, 10, 0), note=note, web=web)
    t = add(p, "tell me when there are new results for 'new laptop launch India'")
    assert t.every_s == 6 * 3600 and t.condition == {"query": "new laptop launch India", "topic": "general"}
    assert poll(p, t.id).status == "baseline"
    web.results = [{"url": "https://news.example/a", "title": "Launch A"},          # same page, no utm
                   {"url": "https://news.example/b", "title": "Launch B"}]
    later(p, hours=6)
    r = poll(p, t.id)
    assert r.status == "fired" and [e.data["url"] for e in r.events] == ["https://news.example/b"]

    web.fail = True
    start = p.now()
    later(p, hours=6)
    r = poll(p, t.id)
    assert r.status == "error"
    trig, _ = get(t.id)
    assert trig.failures == 1 and trig.next_poll_at == (p.now() + timedelta(hours=6)).isoformat()
    p.clock.now = datetime.fromisoformat(trig.next_poll_at)
    poll(p, t.id)
    trig, _ = get(t.id)
    assert trig.failures == 2 and datetime.fromisoformat(trig.next_poll_at) == p.now() + timedelta(hours=6)  # cap 6 h
    assert p.poll_triggers() == []                                  # backing off: not due
    web.fail = False
    p.clock.now = datetime.fromisoformat(trig.next_poll_at)
    assert poll(p, t.id).status == "ok"
    trig, _ = get(t.id)
    assert trig.failures == 0 and start < p.now()


def test_backoff_doubles_up_to_the_cap(isolated):
    web = FakeWeb(fail=True)
    p = make(at(2026, 10, 10, 10, 0), web=web, max_backoff_hours=1)
    t = add(p, "tell me when there are new results for 'x y'", every_s=300)
    rt = open_runtime()
    rt.store.conn.execute("UPDATE trig_triggers SET every_s=300 WHERE id=?", (t.id,))
    rt.store.conn.commit()
    rt.close()
    waits = []
    for _ in range(6):
        poll(p, t.id)
        trig, _ = get(t.id)
        nxt = datetime.fromisoformat(trig.next_poll_at)
        waits.append(int((nxt - p.now()).total_seconds() // 60))
        p.clock.now = nxt
    assert waits == [5, 10, 20, 40, 60, 60]


# ---------------------------------------------------------------- email_from (P2)


def _msg(mid, frm="Boss <boss@example.com>", subject="Quarterly numbers"):
    return {"id": mid, "threadId": "t", "from": frm, "to": "me@example.com", "subject": subject, "date": "",
            "snippet": "SECRET SNIPPET TEXT", "body": "SECRET BODY TEXT", "labelIds": ["INBOX"]}


def test_email_trigger_passes_only_the_id_when_headers_are_p2(isolated):
    google = FakeGoogleClient(messages=[_msg("m1")])
    chats = ScriptedChats(["Noted."])
    note = FakeNotifier()
    p = make(at(2026, 10, 10, 10, 0), chats, note, google=google)
    t = add(p, "when I get an email from boss@example.com, make a short note about it")
    assert t.source == "email_from" and t.condition["sender"] == "boss@example.com"
    assert poll(p, t.id).status == "baseline"                       # m1 existed before
    google.messages["m2"] = _msg("m2")
    google.messages["m3"] = _msg("m3", frm="Someone Else <other@example.com>")       # not from boss
    later(p, minutes=5)
    r = poll(p, t.id)
    assert r.status == "fired" and [e.data for e in r.events] == [{"id": "m2"}]
    sent_to_model = "\n".join(m.text_content() for m in chats.providers[0].requests[0].messages)
    everything = sent_to_model + "\n".join(text for _, text in note.sent) + r.text
    assert "m2" in sent_to_model
    for secret in ("SECRET", "boss@example.com", "Quarterly", "Boss"):
        assert secret not in everything
    assert chats.approvers  # ran with the unattended approver


def test_email_trigger_headers_when_p1_but_never_body(isolated):
    google = FakeGoogleClient(messages=[])
    note = FakeNotifier()
    p = make(at(2026, 10, 10, 10, 0), note=note, google=google, header_class="P1")
    t = add(p, "when an email with subject quarterly arrives, tell me")
    poll(p, t.id)
    google.messages["m9"] = _msg("m9")
    later(p, minutes=5)
    r = poll(p, t.id)
    assert r.status == "fired" and r.events[0].data["subject"] == "Quarterly numbers"
    assert "boss@example.com" in note.sent[0][1] and "SECRET" not in note.sent[0][1]


def test_email_action_is_tainted_so_even_t1_waits(isolated):
    google = FakeGoogleClient(messages=[])
    chats = ScriptedChats([{"tool": "write_file", "arguments": {"path": "mail-note.md", "content": "x"}}, "ok"])
    p = make(at(2026, 10, 10, 10, 0), chats, google=google)
    t = add(p, "when I get an email from boss@example.com, write a note")
    poll(p, t.id)
    google.messages["m2"] = _msg("m2")
    later(p, minutes=5)
    r = poll(p, t.id)
    assert r.pending == 1 and not (isolated / "workspace" / "mail-note.md").exists()


def test_email_trigger_waits_while_google_is_not_connected(isolated):
    p = make(at(2026, 10, 10, 10, 0), google=None)
    t = add(p, "when I get an email from boss@example.com tell me")
    r = poll(p, t.id)
    assert r.status == "waiting" and "not connected" in r.detail
    trig, _ = get(t.id)
    assert trig.failures == 0 and trig.state == {}                  # no baseline yet either


def test_gmail_failure_is_recorded_and_backed_off(isolated):
    google = FakeGoogleClient(fail=True)
    p = make(at(2026, 10, 10, 10, 0), google=google)
    t = add(p, "when I get an email from boss@example.com tell me")
    r = poll(p, t.id)
    assert r.status == "error" and "fake network failure" in r.detail
    trig, _ = get(t.id)
    assert trig.failures == 1 and trig.last_status == "error"


# ---------------------------------------------------------------- calendar_soon


def _event(eid, start, title="Design review"):
    return {"id": eid, "summary": title, "start": {"dateTime": start.isoformat()},
            "end": {"dateTime": (start + timedelta(minutes=30)).isoformat()}}


def test_calendar_soon_fires_once_per_event(isolated):
    now = at(2026, 10, 10, 10, 0)
    google = FakeGoogleClient(events=[_event("e1", now + timedelta(minutes=10)),
                                      _event("e2", now + timedelta(minutes=40), "Lunch")])
    note = FakeNotifier()
    p = make(now, note=note, google=google)
    t = add(p, "15 minutes before a meeting remind me")
    r = poll(p, t.id)
    assert r.status == "fired" and "'Design review' starts at 10:10 (in 10 min)" in note.sent[0][1]
    later(p, minutes=5)
    assert poll(p, t.id).status == "ok" and len(note.sent) == 1
    later(p, minutes=25)                                            # 10:30: Lunch at 10:40 is now within 15 min
    r = poll(p, t.id)
    assert r.status == "fired" and "Lunch" in note.sent[1][1]


# ---------------------------------------------------------------- store, service, dashboard


def test_claim_is_atomic_per_key(isolated):
    rt = open_runtime()
    store = TriggerStore(rt.store.conn)
    now = at(2026, 10, 10, 10, 0)
    assert store.claim("t-001", "k", now) is True
    assert store.claim("t-001", "k", now) is False
    assert store.claim("t-002", "k", now) is True
    rt.close()


def test_pause_resume_delete(isolated):
    (isolated / "workspace" / "inbox").mkdir(parents=True)
    p = make(at(2026, 10, 10, 10, 0))
    t = add(p, "when a new file arrives in workspace/inbox tell me")
    rt = open_runtime()
    store = TriggerStore(rt.store.conn)
    store.set_enabled(t.id, False, p.now())
    rt.close()
    assert p.poll_triggers() == [] and poll(p, t.id).status == "paused"
    rt = open_runtime()
    store = TriggerStore(rt.store.conn)
    store.set_enabled(t.id, True, p.now())
    assert store.delete(t.id) and store.get(t.id) is None
    rt.close()


def test_daemon_service_runs_the_trigger_poller(isolated):
    p = make(at(2026, 10, 10, 10, 0))
    jobs = {job_id: every for _, every, job_id in p.service().extra_jobs}
    assert jobs["_triggers"] == 60 and "_reminders" in jobs
    off = make(at(2026, 10, 10, 10, 0), enabled=False)
    assert "_triggers" not in {j for _, _, j in off.service().extra_jobs}
    assert off.poll_triggers() == []


def test_dashboard_hook_lists_triggers_without_email_senders(isolated):
    (isolated / "workspace" / "inbox").mkdir(parents=True)
    p = make(at(2026, 10, 10, 10, 0))
    add(p, "when a new file arrives in workspace/inbox tell me")
    add(p, "when I get an email from boss@example.com tell me")
    data = dashboard_triggers(isolated)
    assert [i["source"] for i in data["items"]] == ["file_new", "email_from"]
    assert "boss@example.com" not in str(data)
    assert data["items"][0]["enabled"] is True and data["items"][0]["every_minutes"] == 2
