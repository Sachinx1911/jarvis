"""Phase 9 part G: the voice-route table and its wiring in the voice loop (fake speaker, fake teardown)."""

from __future__ import annotations

import io
import json
from datetime import datetime

import pytest

from jarvis.config import load_config
from jarvis.control.audit import AuditLog
from jarvis.core.chat import ChatSession
from jarvis.db import Store
from jarvis.memory.extract import Extractor
from jarvis.memory.store import MemoryStore
from jarvis.providers.fake import FakeProvider
from jarvis.routing.policy import RouteDecision
from jarvis.tools.system import SystemTools
from jarvis.tools.web import WebClient
from jarvis.voice.config import load_voice_config
from jarvis.voice.loop import STOP_SPEAKING, VoiceLoop
from jarvis.voice.recorder import FakeRecorder
from jarvis.voice.routes import ROUTES, match_voice_route
from jarvis.voice.stt import FakeSTT
from jarvis.voice.tts import FakeTTS, SpeechOutput
from jarvis.voice.xray_bridge import VoiceXray
from jarvis.xray.front_tab import FrontTab

MAIN = RouteDecision("main_chat", "fake", "fake-1", "medium", "test")


# ---- the table ----

@pytest.mark.parametrize("said", ["stop", "Stop!", "jarvis stop", "wait", "hold on", "थांब", "थांबा", "जरा थांब"])
def test_stop_words(said):
    route, args = match_voice_route(said)
    assert route.name == "stop" and args == {}


def test_stop_speaking_is_still_exported_from_the_loop():
    assert "stop" in STOP_SPEAKING and "थांब" in STOP_SPEAKING


@pytest.mark.parametrize("said, text", [
    ("remember that the office key is under the mat", "the office key is under the mat"),
    ("Jarvis, remember that Ravi likes chai.", "Ravi likes chai"),
    ("remember this: the car service is on Monday", "the car service is on Monday"),
    ("लक्षात ठेव उद्या मीटिंग दहा वाजता आहे", "उद्या मीटिंग दहा वाजता आहे"),
    ("उद्या मीटिंग दहा वाजता आहे हे लक्षात ठेव", "उद्या मीटिंग दहा वाजता आहे"),
])
def test_remember_route(said, text):
    route, args = match_voice_route(said)
    assert route.name == "remember" and args == {"text": text}


@pytest.mark.parametrize("said", ["show me the last teardown", "last teardown", "open the latest teardown note",
                                  "शेवटचं teardown दाखव"])
def test_show_last_teardown_route(said):
    assert match_voice_route(said)[0].name == "show_last_teardown"


def test_teardown_route_carries_url_and_question():
    route, args = match_voice_route("reverse engineer igloo dot inc")
    assert route.name == "teardown" and args == {"url": "https://igloo.inc", "question": "reverse engineer igloo dot inc"}
    assert match_voice_route("tear down this site")[1]["url"] == "this site"
    assert match_voice_route("igloo.inc कसं बनवलंय")[1]["url"] == "https://igloo.inc"


@pytest.mark.parametrize("said", ["what time is it", "good evening jarvis", "remember", "", "stop the music please"])
def test_plain_sentences_go_to_the_brain(said):
    assert match_voice_route(said) is None


def test_routes_are_checked_in_order_stop_first():
    assert [r.name for r in ROUTES] == ["stop", "remember", "show_last_teardown", "teardown"]


# ---- the loop ----

@pytest.fixture
def env(tmp_path):
    store = Store(tmp_path / "data" / "jarvis.db")
    yield tmp_path, store
    store.close()


class FakeXray:
    """Clearly a fake: no kit, no Chrome. It records what the loop asked for."""

    def __init__(self):
        self.started: list[tuple] = []

    def start(self, url, question):
        self.started.append((url, question))
        return f"Starting the teardown of {url}."

    def last(self):
        return "The last teardown is igloo.inc-2026-10-17. Three.js and GSAP."


def _session(env, script=None, with_memory=True):
    home, store = env
    audit = AuditLog(home / "data" / "audit.jsonl")
    memory = MemoryStore(home, store)
    extractor = Extractor(memory, None, None, audit) if with_memory else None   # no model: plain remember
    return ChatSession(load_config(), FakeProvider(script=script), MAIN, store, audit,
                       now=lambda: datetime(2026, 10, 17, 19, 30), home=home, memory=memory, extractor=extractor,
                       web=WebClient(transport=lambda *a: (404, b""), check_url=lambda u: None),
                       system=SystemTools(apps={}, runner=lambda a: None, opener=lambda u: True))


def _loop(env, session, xray=None, inp=""):
    home, _ = env
    tts = FakeTTS("local")
    speech = SpeechOutput(tts, None, "P1", session.audit)
    loop = VoiceLoop(session, FakeSTT([]), speech, FakeRecorder(), session.audit, session.stop, load_voice_config(),
                     io.StringIO(), io.StringIO(inp), home, xray=xray)
    return loop, tts


def _audit(home):
    return [json.loads(l) for l in (home / "data" / "audit.jsonl").read_text(encoding="utf-8").splitlines()]


def test_remember_route_saves_a_memory_and_speaks_a_short_confirmation(env):
    home, store = env
    session = _session(env)
    loop, tts = _loop(env, session)
    result = loop.handle_text("remember that the office key is under the mat")
    assert result.status == "routed" and result.reply.startswith("Remembered: ")
    assert session.provider.requests == []   # the brain was not asked
    mems = MemoryStore(home, store).list()
    assert len(mems) == 1 and mems[0].body == "the office key is under the mat" and mems[0].source == "user-said"
    assert tts.spoken[0][0] == result.reply
    turn = [e for e in _audit(home) if e["event"] == "voice_turn"][-1]
    assert turn["status"] == "routed" and turn["detail"] == "route:remember"


def test_remember_in_marathi_confirms_in_marathi(env):
    loop, tts = _loop(env, _session(env))
    result = loop.handle_text("लक्षात ठेव उद्या मीटिंग दहा वाजता आहे")
    assert result.reply.startswith("लक्षात ठेवलं: ")


def test_remember_without_memory_says_so(env):
    loop, _ = _loop(env, _session(env, with_memory=False))
    assert loop.handle_text("remember that x is y").reply == "Memory is not available."


def test_remember_refuses_a_secret(env):
    home, store = env
    loop, _ = _loop(env, _session(env))
    result = loop.handle_text("remember that my password is hunter2hunter2")
    assert result.reply.startswith("Not saved:") and MemoryStore(home, store).list() == []


def test_stop_route_silences_without_the_brain(env):
    session = _session(env)
    loop, tts = _loop(env, session)
    loop.handle_text("hello")
    assert loop.handle_text("wait").status == "stopped_speaking"
    assert loop.handle_text("थांब").status == "stopped_speaking"
    assert len(session.provider.requests) == 1


def test_teardown_route_starts_the_job_through_the_bridge(env):
    session = _session(env)
    xray = FakeXray()
    loop, tts = _loop(env, session, xray=xray)
    result = loop.handle_text("reverse engineer igloo dot inc")
    assert result.status == "routed" and xray.started == [("https://igloo.inc", "reverse engineer igloo dot inc")]
    assert tts.spoken[-1][0] == "Starting the teardown of https://igloo.inc."
    assert session.provider.requests == []
    assert loop.handle_text("show me the last teardown").reply.startswith("The last teardown is igloo.inc")


def test_plain_sentence_still_reaches_the_brain(env):
    session = _session(env, ["Good evening, sir."])
    loop, _ = _loop(env, session, xray=FakeXray())
    assert loop.handle_text("hello jarvis").status == "replied" and len(session.provider.requests) == 1


# ---- the bridge itself, with fakes for the kit, the deps and the runner ----

def _bridge(env, diag, deps_factory=None, front=None, inp="", runner=None):
    home, store = env
    session = _session(env)
    out = io.StringIO()
    bridge = VoiceXray(session, home, session.audit, out, io.StringIO(inp), deps_factory=deps_factory, diag=diag,
                       front=front, runner=runner)
    return bridge, out


def test_bridge_says_the_diag_problem_when_the_kit_is_not_ready(env):
    bridge, _ = _bridge(env, diag=lambda: {"ready": False, "problems": ["node not found", "REA not installed"]})
    reply = bridge.start("https://igloo.inc", "how")
    assert reply.startswith("The teardown kit is not ready: node not found; REA not installed")
    assert bridge.jobs == []


def test_bridge_starts_a_job_when_ready(env):
    runs = []
    bridge, _ = _bridge(env, diag=lambda: {"ready": True, "problems": []}, deps_factory=lambda: "fake deps",
                        runner=lambda url, q, deps: runs.append((url, q, deps)))
    assert bridge.start("https://igloo.inc", "how does igloo.inc do that") == \
        "Starting the teardown of igloo.inc. The note lands in workspace/teardowns when it is done."
    assert runs == [("https://igloo.inc", "how does igloo.inc do that", "fake deps")]
    assert bridge.start("https://igloo.inc", "igloo.inc कसं बनवलंय").startswith("igloo.inc चं teardown सुरू")


def test_bridge_handles_a_missing_kit_module(env):
    def missing():
        raise ImportError("No module named jarvis.xray.kit")

    bridge, _ = _bridge(env, diag=lambda: {"ready": True, "problems": []}, deps_factory=missing)
    assert bridge.start("https://igloo.inc", "how").startswith("The teardown kit is not available")


def test_bridge_asks_for_an_address_when_none_was_heard(env):
    bridge, _ = _bridge(env, diag=lambda: {"ready": True, "problems": []})
    assert bridge.start(None, "reverse engineer Stripe's homepage").startswith("Which site?")


def test_bridge_this_site_confirms_the_front_tab_on_screen(env):
    runs = []
    front = lambda: FrontTab("https://igloo.inc/", "front tab of Google Chrome (osascript)")  # noqa: E731
    bridge, out = _bridge(env, diag=lambda: {"ready": True, "problems": []}, deps_factory=lambda: "d",
                          front=front, inp="y\n", runner=lambda u, q, d: runs.append(u))
    assert bridge.start("this site", "tear down this site").startswith("Starting the teardown of igloo.inc")
    assert "Front tab address: https://igloo.inc/" in out.getvalue() and runs == ["https://igloo.inc/"]
    # not confirmed: nothing starts
    bridge, _ = _bridge(env, diag=lambda: {"ready": True, "problems": []}, front=front, inp="\n",
                        runner=lambda u, q, d: runs.append(u))
    assert bridge.start("this site", "tear down this site").startswith("Left it.") and runs == ["https://igloo.inc/"]
    # no front tab (Windows): the reason is the answer
    bridge, _ = _bridge(env, diag=lambda: {"ready": True, "problems": []},
                        front=lambda: FrontTab(None, "not supported yet on Windows"))
    assert bridge.start("this site", "tear down this site") == "not supported yet on Windows"


def test_bridge_last_without_notes(env):
    bridge, _ = _bridge(env, diag=lambda: {"ready": False, "problems": []})
    assert bridge.last().startswith("There is no teardown yet")
