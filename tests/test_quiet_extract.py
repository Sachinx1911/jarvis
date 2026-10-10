"""Memory extraction after a quiet session (PLAN.md 6.3 rule 8). Offline: fake provider, fake clock."""

import json

from jarvis.core.runtime import open_runtime
from jarvis.memory.extract import Extractor
from jarvis.memory.quiet import (
    extract_quiet_sessions, extraction_record, is_extracted, mark_extracted, quiet_sessions,
    unextracted_user_messages,
)
from jarvis.proactive.scheduler import ScheduleStore
from jarvis.providers.base import Message
from jarvis.providers.fake import FakeProvider
from jarvis.routing.policy import RouteDecision

from test_proactive_support import at, proactive

DECISION = RouteDecision("memory_extractor", "fake", "fake-1", "low", "test")
NOW = at(2026, 10, 12, 10, 0)          # 04:30 UTC; messages.ts is UTC
CHAT = "a1b2c3d4e5f6"                   # ChatSession ids are 12 hex characters
CHAT2 = "0f0f0f0f0f0f"


def _cand(**kw):
    base = {"name": "tea preference", "type": "preference", "subject": "user", "summary_en": "The user likes tea.",
            "keywords": "tea chai", "when_to_use": "drinks", "sensitivity": "normal",
            "evidence": "mala chai avadte", "source": "user-said", "body": "likes tea (chai)"}
    return {**base, **kw}


def _add(rt, sid, role, text, ts):
    mid = rt.store.add_message(sid, Message.text(role, text))
    rt.store.conn.execute("UPDATE messages SET ts=? WHERE id=?", (ts, mid))
    rt.store.conn.commit()
    return mid


def _chat(rt, sid=CHAT, last="2026-10-12 04:05:00", user=("namaskar", "mala chai avadte")):
    _add(rt, sid, "user", user[0], last)
    _add(rt, sid, "assistant", "Noted, sir. You like coffee too?", last)
    for text in user[1:]:
        _add(rt, sid, "user", text, last)


def _extractor(rt, script):
    provider = FakeProvider(script=script)
    return Extractor(rt.memory, provider, DECISION, rt.audit), provider


def _events(rt):
    path = rt.paths.audit_log
    return [json.loads(l)["event"] for l in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def test_quiet_session_is_extracted_once_from_user_messages_only():
    rt = open_runtime()
    try:
        _chat(rt)                                                  # last message 25 minutes ago
        ex, provider = _extractor(rt, [{"json": {"candidates": [_cand()]}}])
        run = extract_quiet_sessions(rt.store.conn, ex, NOW)
        assert [o.status for o in run.outcomes] == ["extracted"]
        assert run.saved and rt.memory.get(run.saved[0]).evidence == "mala chai avadte"
        sent = provider.requests[0].messages[0].text_content()
        assert "mala chai avadte" in sent and "namaskar" in sent
        assert "coffee" not in sent                                # Jarvis's reply never reaches the extractor
        assert is_extracted(rt.store.conn, CHAT)
        assert extraction_record(rt.store.conn, CHAT)["source"] == "quiet"
        again = extract_quiet_sessions(rt.store.conn, ex, NOW.replace(minute=10))
        assert again.outcomes == [] and len(provider.requests) == 1      # not twice
        assert "session_extracted" in _events(rt)
    finally:
        rt.close()


def test_recent_session_waits_until_quiet():
    rt = open_runtime()
    try:
        _chat(rt, last="2026-10-12 04:25:00")                      # 5 minutes ago: still going
        assert quiet_sessions(rt.store.conn, NOW, quiet_minutes=20) == []
        assert quiet_sessions(rt.store.conn, NOW.replace(minute=20), quiet_minutes=20) == [CHAT]   # 25 min later
        assert quiet_sessions(rt.store.conn, NOW, quiet_minutes=3) == [CHAT]                       # configurable
    finally:
        rt.close()


def test_session_extracted_at_exit_is_not_extracted_again():
    rt = open_runtime()
    try:
        _chat(rt)
        mark_extracted(rt.store.conn, CHAT, [("ADD", "m-0001")])  # the ChatSession.end() hook
        assert extraction_record(rt.store.conn, CHAT)["source"] == "end"
        ex, provider = _extractor(rt, [{"json": {"candidates": [_cand()]}}])
        assert extract_quiet_sessions(rt.store.conn, ex, NOW).outcomes == []
        assert provider.requests == []
    finally:
        rt.close()


def test_only_new_messages_after_an_earlier_extraction():
    rt = open_runtime()
    try:
        _chat(rt, last="2026-10-12 03:00:00")
        mark_extracted(rt.store.conn, CHAT, [])
        _add(rt, CHAT, "user", "udya sakali 9 la bank madhe jaycha ahe", "2026-10-12 04:05:00")   # came back later
        assert unextracted_user_messages(rt.store.conn, CHAT) == ["udya sakali 9 la bank madhe jaycha ahe"]
        ex, provider = _extractor(rt, [{"json": {"candidates": []}}])
        run = extract_quiet_sessions(rt.store.conn, ex, NOW)
        assert [o.status for o in run.outcomes] == ["extracted"]
        sent = provider.requests[0].messages[0].text_content()
        assert "bank madhe" in sent and "mala chai" not in sent
    finally:
        rt.close()


def test_task_runs_and_unattended_schedule_turns_are_skipped():
    rt = open_runtime()
    try:
        _chat(rt, sid="t-001")                                      # a task, not a chat
        _chat(rt, sid=CHAT2, user=("[Scheduled run of s-001 'x'. Sachin is not watching ...] summary", "more"))
        _chat(rt, sid=CHAT, user=("मला चहा आवडतो",))               # Devanagari chat: counts
        assert quiet_sessions(rt.store.conn, NOW) == [CHAT]
    finally:
        rt.close()


def test_old_sessions_are_not_backfilled():
    rt = open_runtime()
    try:
        _chat(rt, last="2026-10-10 04:00:00")                      # two days old
        assert quiet_sessions(rt.store.conn, NOW, max_age_hours=24) == []
    finally:
        rt.close()


def test_failed_extraction_is_retried_then_given_up():
    rt = open_runtime()
    try:
        _chat(rt)
        ex, provider = _extractor(rt, ["not json", "still not json", "nope"])
        statuses = [extract_quiet_sessions(rt.store.conn, ex, NOW, max_failures=3).outcomes[0].status
                    for _ in range(3)]
        assert statuses == ["failed", "failed", "gave_up"]
        assert not is_extracted(rt.store.conn, CHAT)
        assert extract_quiet_sessions(rt.store.conn, ex, NOW, max_failures=3).outcomes == []
        assert len(provider.requests) == 3
        assert "quiet_extract_failed" in _events(rt)
    finally:
        rt.close()


def test_no_model_route_skips_without_marking():
    rt = open_runtime()
    try:
        _chat(rt)
        run = extract_quiet_sessions(rt.store.conn, Extractor(rt.memory, None, None, rt.audit), NOW,
                                     audit=rt.audit)
        assert run.skipped_reason and not is_extracted(rt.store.conn, CHAT)
    finally:
        rt.close()


def _schedule_kind(kind):
    rt = open_runtime()
    try:
        return next(s for s in ScheduleStore(rt.store.conn).list() if s.kind == kind)
    finally:
        rt.close()


def test_memory_extract_schedule_runs_through_the_scheduler():
    providers = []

    def factory(rt):
        provider = FakeProvider(script=[{"json": {"candidates": [_cand()]}}])
        providers.append(provider)
        return Extractor(rt.memory, provider, DECISION, rt.audit)

    p = proactive(NOW)
    p.extractor_factory = factory
    p.ensure_default_schedules()
    s = _schedule_kind("memory_extract")
    assert p.runner().run(s.id, "cron").status == "quiet"           # nothing to extract yet
    rt = open_runtime()
    _chat(rt)
    rt.close()
    result = p.runner().run(s.id, "cron")
    assert result.status == "ok" and CHAT in result.text and "ADD m-" in result.text
    assert result.output_path and "Memory extraction" in open(result.output_path, encoding="utf-8").read()
    assert p.runner().run(s.id, "cron").status == "quiet"           # extracted once only
