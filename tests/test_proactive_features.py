"""Heartbeat, daily brief, reminders, notifier and the cloud override."""

import json
from datetime import timedelta

import pytest

from jarvis.config import load_config
from jarvis.control.audit import AuditLog
from jarvis.control.stop import StopSwitch
from jarvis.core.runtime import open_runtime
from jarvis.proactive import brief as brief_mod
from jarvis.proactive.brief import BriefContext, build_brief, register_section, registered_sections
from jarvis.proactive.cloud import apply_cloud_override, cloud_override, effective_cloud_allowed, set_cloud_override
from jarvis.proactive.heartbeat import Heartbeat, heartbeat_path, read_checklist
from jarvis.proactive.notify import ConsoleNotifier, FallbackNotifier, TelegramNotifier, make_notifier
from jarvis.proactive.reminders import ReminderStore
from jarvis.proactive.settings import decide_route, with_routes
from jarvis.providers.fake import FakeProvider
from jarvis.routing.policy import RouteDecision, RoutingError
from jarvis.tasks.store import TaskStore
from jarvis.telegram.sender import TelegramSender, TelegramSendError, chunks
from jarvis.tools.web import WebClient

from test_proactive_support import FakeNotifier, at, proactive, settings

HB = RouteDecision("heartbeat", "fake", "fake-1", "low", "test")


@pytest.fixture
def rt():
    runtime = open_runtime()
    yield runtime
    runtime.close()


def _heartbeat(rt, script=None, **over):
    provider = FakeProvider(script=script or [])
    return Heartbeat(rt.paths.home, settings(**over), rt.store.conn, rt.audit, provider, HB, rt.store), provider


def _checklist(rt, *items):
    heartbeat_path(rt.paths.home).parent.mkdir(parents=True, exist_ok=True)
    heartbeat_path(rt.paths.home).write_text("# HEARTBEAT\n" + "".join(f"- {i}\n" for i in items), encoding="utf-8")


# ---- heartbeat ----

def test_heartbeat_template_created_and_has_no_active_items(rt):
    assert read_checklist(rt.paths.home) == []
    assert heartbeat_path(rt.paths.home).exists()
    hb, provider = _heartbeat(rt)
    result = hb.run(at(2026, 10, 10, 15, 0))
    assert not result.spoke and result.reason == "checklist is empty"
    assert provider.requests == []                       # no model call for an empty list


def test_heartbeat_speaks_when_it_matters_and_sees_facts(rt):
    _checklist(rt, "If a task has failed, tell me once.")
    tasks = TaskStore(rt.store, rt.paths.data / "tasks")
    t = tasks.create("Compare three laptops")
    tasks.set_state(t.id, "FAILED", "website timeout")
    hb, provider = _heartbeat(rt, [{"json": {"speak": True, "message": "Sir, task t-001 failed.",
                                             "reason": "failed task"}}])
    result = hb.run(at(2026, 10, 10, 15, 0))
    assert result.spoke and result.message == "Sir, task t-001 failed."
    sent = provider.requests[0].messages[0].text_content()
    assert "Task t-001 'Compare three laptops' is FAILED" in sent
    assert provider.requests[0].route == "heartbeat"


def test_heartbeat_stays_quiet_when_nothing_matters(rt):
    _checklist(rt, "Tell me if anything failed.")
    hb, _ = _heartbeat(rt, [{"json": {"speak": False, "message": "", "reason": "all fine"}}])
    assert not hb.run(at(2026, 10, 10, 15, 0)).spoke


def test_heartbeat_does_not_repeat_itself(rt):
    _checklist(rt, "Tell me if anything failed.")
    say = {"json": {"speak": True, "message": "Sir, task t-001 failed.", "reason": "x"}}
    hb, _ = _heartbeat(rt, [say, say, say])
    assert hb.run(at(2026, 10, 10, 15, 0)).spoke
    second = hb.run(at(2026, 10, 10, 15, 30))
    assert not second.spoke and second.reason == "already said recently"
    assert hb.run(at(2026, 10, 10, 21, 31)).spoke         # after repeat_after_hours (6 h)


def test_heartbeat_quiet_hours_and_stop_make_no_model_call(rt):
    _checklist(rt, "Tell me if anything failed.")
    hb, provider = _heartbeat(rt)
    assert hb.run(at(2026, 10, 10, 23, 15)).reason == "quiet hours"
    assert hb.run(at(2026, 10, 11, 6, 59)).reason == "quiet hours"
    StopSwitch(rt.paths.data).engage("test")
    assert hb.run(at(2026, 10, 11, 12, 0)).reason == "emergency stop is on"
    assert provider.requests == []


def test_heartbeat_bad_model_answer_is_silent(rt):
    _checklist(rt, "x")
    hb, _ = _heartbeat(rt, ["not json"])
    result = hb.run(at(2026, 10, 10, 15, 0))
    assert not result.spoke and result.model_called


def test_quiet_hours_window():
    s = settings()
    assert s.in_quiet_hours(at(2026, 10, 10, 22, 30)) and s.in_quiet_hours(at(2026, 10, 11, 3, 0))
    assert not s.in_quiet_hours(at(2026, 10, 11, 7, 0)) and not s.in_quiet_hours(at(2026, 10, 10, 12, 0))


# ---- brief ----

class _Boom:
    key, title, order = "boom", "Broken", 15

    def render(self, ctx):
        raise RuntimeError("API down")


def _weather_transport(method, url, headers, body):
    if "geocoding" in url:
        return 200, json.dumps({"results": [{"name": "Testville", "latitude": 1, "longitude": 2,
                                             "country": "Nowhere"}]}).encode()
    return 200, json.dumps({"current": {"temperature_2m": 28, "apparent_temperature": 30, "weather_code": 1,
                                        "wind_speed_10m": 5},
                            "daily": {"time": ["2026-10-10"], "weather_code": [61], "temperature_2m_min": [22],
                                      "temperature_2m_max": [31], "precipitation_probability_max": [60]}}).encode()


def test_brief_assembles_sections_and_isolates_a_failure(rt):
    tasks = TaskStore(rt.store, rt.paths.data / "tasks")
    tasks.create("Renew the parking pass")
    ReminderStore(rt.store.conn).add("call the plumber", at(2026, 10, 10, 18, 0), now=at(2026, 10, 10, 7, 0))
    (rt.paths.home / "profile" / "goals.md").write_text("- Walk 30 minutes a day\n- [x] done goal\n", encoding="utf-8")
    s = settings(brief={"place": "Testville"})
    ctx = BriefContext(at(2026, 10, 10, 8, 0), rt.paths.home, rt.store, s,
                       {"web": WebClient(transport=_weather_transport, check_url=lambda u: None)})
    sections = registered_sections() + [_Boom()]
    sections.sort(key=lambda x: x.order)
    b = build_brief(ctx, sections, rt.audit)
    assert b.failed == ["boom"]
    text = b.text
    assert "Broken\nUnavailable right now." in text
    assert "28°C" in text and "rain chance 60%" in text
    assert "- 18:00 call the plumber" in text
    assert "t-001 [BACKLOG] Renew the parking pass" in text
    assert "Walk 30 minutes a day" in text and "done goal" not in text
    assert "Calendar\nNot connected yet (Phase 5)." in text
    assert text.index("Weather") < text.index("Broken") < text.index("Calendar") < text.index("Reminders today")


def test_connectors_can_replace_placeholder_sections(rt, monkeypatch):
    monkeypatch.setattr(brief_mod, "_REGISTRY", dict(brief_mod._REGISTRY))

    class Calendar:
        key, title, order = "calendar", "Calendar", 20

        def render(self, ctx):
            return "- 11:00 call with the bank"
    register_section(Calendar())
    ctx = BriefContext(at(2026, 10, 10, 8, 0), rt.paths.home, rt.store, settings())
    text = build_brief(ctx).text
    assert "Calendar\n- 11:00 call with the bank" in text and "Not connected yet (Phase 5).\n\nReminders" not in text


def test_brief_without_place_says_how_to_set_it(rt):
    ctx = BriefContext(at(2026, 10, 10, 8, 0), rt.paths.home, rt.store, settings())
    assert "No default place set" in build_brief(ctx).text


# ---- reminders ----

def test_reminders_fire_once_when_due(rt):
    store = ReminderStore(rt.store.conn, rt.audit)
    r = store.add("drink water", at(2026, 10, 10, 15, 10), now=at(2026, 10, 10, 15, 0))
    note = FakeNotifier()
    assert store.fire_due(at(2026, 10, 10, 15, 9), note) == []
    assert [x.id for x in store.fire_due(at(2026, 10, 10, 15, 10), note)] == [r.id]
    assert note.sent == [("Reminder", "Reminder: drink water")]
    assert store.fire_due(at(2026, 10, 10, 15, 11), note) == []      # not twice
    assert store.get(r.id).status == "sent"


def test_reminder_due_while_off_is_sent_late(rt):
    store = ReminderStore(rt.store.conn)
    store.add("submit the form", at(2026, 10, 10, 9, 0), now=at(2026, 10, 10, 8, 0))
    note = FakeNotifier()
    store.fire_due(at(2026, 10, 10, 11, 0), note)
    assert "late: it was due at 09:00" in note.sent[0][1]


def test_reminder_kept_when_sending_fails(rt):
    store = ReminderStore(rt.store.conn)
    r = store.add("x", at(2026, 10, 10, 9, 0), now=at(2026, 10, 10, 8, 0))
    assert store.fire_due(at(2026, 10, 10, 9, 0), FakeNotifier(fail=True)) == []
    assert store.get(r.id).status == "pending"
    assert store.fire_due(at(2026, 10, 10, 9, 1), FakeNotifier()) != []


def test_reminder_cancel(rt):
    store = ReminderStore(rt.store.conn)
    r = store.add("x", at(2026, 10, 10, 9, 0), now=at(2026, 10, 10, 8, 0))
    assert store.cancel(r.id) and store.pending() == []


def test_daemon_reminder_job_uses_the_notifier():
    note = FakeNotifier()
    p = proactive(at(2026, 10, 10, 15, 0), notifier=note)
    rt = open_runtime()
    ReminderStore(rt.store.conn).add("stretch", at(2026, 10, 10, 15, 0), now=at(2026, 10, 10, 14, 0))
    rt.close()
    assert p.fire_reminders() == 1 and note.sent[0][1] == "Reminder: stretch"


# ---- notifier ----

def test_notifier_falls_back_in_order(tmp_path):
    bad, good = FakeNotifier(fail=True), FakeNotifier()
    bad.name = "telegram"
    n = FallbackNotifier([bad, good], AuditLog(tmp_path / "a.jsonl"))
    assert n.send("hello") == "fake"
    assert good.sent == [("Jarvis", "hello")]


def test_make_notifier_order(monkeypatch):
    class Sender:
        def __init__(self):
            self.sent = []

        def send(self, text):
            self.sent.append(text)
    sender = Sender()
    n = make_notifier(settings(), telegram=sender, desktop=False)
    assert [c.name for c in n.channels] == ["telegram", "console"]
    n.send("brief text", "Daily brief")
    assert sender.sent == ["Daily brief\nbrief text"]
    n2 = make_notifier(settings(), desktop=False)          # no token in the (test) keyring
    assert [c.name for c in n2.channels] == ["console"]


def test_console_notifier(capsys):
    ConsoleNotifier().send("hi", "Reminder")
    assert "[Reminder] hi" in capsys.readouterr().out


def test_telegram_sender_never_leaks_the_token():
    calls = []

    def transport(url, body):
        calls.append((url, json.loads(body)))
        return 200, b'{"ok": true, "result": {}}'
    s = TelegramSender("123456:SECRET-TOKEN-abc", 1111, transport)
    s.send("hello")
    assert calls[0][0].endswith("/bot123456:SECRET-TOKEN-abc/sendMessage")
    assert calls[0][1]["chat_id"] == 1111 and calls[0][1]["text"] == "hello"
    assert "SECRET" not in repr(s)
    bad = TelegramSender("123456:SECRET-TOKEN-abc", 1111, lambda u, b: (401, b'{"ok": false, "description": "Unauthorized"}'))
    with pytest.raises(TelegramSendError) as e:
        bad.send("x")
    assert "SECRET" not in str(e.value)
    TelegramNotifier(s).send("t")


def test_long_messages_are_split():
    parts = chunks("line\n" * 2000, size=1000)
    assert all(len(p) <= 1000 for p in parts) and "".join(parts).count("line") == 2000


# ---- cloud override ----

def test_cloud_override_switches_cloud_off_and_back(isolated):
    config = load_config()
    assert cloud_override() is None and effective_cloud_allowed(config)
    set_cloud_override(False)
    assert cloud_override() is False and not effective_cloud_allowed(config)
    assert apply_cloud_override(config).routing["cloud_allowed"] is False
    assert config.routing["cloud_allowed"] is True                 # the shared config is not changed
    with pytest.raises(RoutingError):
        decide_route(config, settings(routes=_ROUTES), "heartbeat")
    set_cloud_override(True)                                       # "on" = back to routing.yaml
    assert cloud_override() is None
    assert decide_route(config, settings(routes=_ROUTES), "heartbeat").provider == "claude_code"


def test_broken_override_file_fails_closed(isolated):
    (isolated / "data").mkdir(exist_ok=True)
    (isolated / "data" / "cloud_override.json").write_text("{not json", encoding="utf-8")
    assert cloud_override() is False


_ROUTES = {"heartbeat": {"candidates": [{"provider": "claude_code", "model": "claude-haiku-5-5", "effort": "low"}],
                         "needs": ["structured_output"], "max_privacy": "P1"}}


def test_module_routes_are_added_in_memory_only():
    config = load_config()
    extended = with_routes(config, settings(routes=_ROUTES))
    assert "heartbeat" in extended.routing["routes"] and "heartbeat" not in config.routing["routes"]
    assert "main_chat" in extended.routing["routes"]


def test_shipped_proactive_config_routes_resolve():
    from jarvis.proactive.settings import load_settings

    s = load_settings()
    for route in ("schedule_parser", "heartbeat"):
        assert decide_route(load_config(), s, route).model == "claude-haiku-5-5"
    assert s.tz_name == "Asia/Kolkata"
