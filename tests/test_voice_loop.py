"""Phase 6 voice loop: fake recorder -> fake STT -> chat (fake provider) -> fake TTS, approvals, stop, CLI."""

import io
import json
import math
import sqlite3
from array import array
from datetime import datetime
from types import SimpleNamespace

import pytest

from jarvis import cli_voice
from jarvis.config import load_config
from jarvis.control.approvals import ApprovalRequest
from jarvis.control.audit import AuditLog
from jarvis.control.stop import StopSwitch
from jarvis.core.chat import ChatSession
from jarvis.db import Store
from jarvis.memory.store import MemoryStore
from jarvis.providers.fake import FakeProvider
from jarvis.routing.policy import RouteDecision
from jarvis.tools.system import SystemTools
from jarvis.tools.web import WebClient
from jarvis.voice.approval import is_explicit_yes, voice_approver
from jarvis.voice.base import Audio, Transcript
from jarvis.voice.config import load_voice_config
from jarvis.voice.loop import REPEAT, VoiceLoop, VoiceStyleContext, voice_style
from jarvis.voice.recorder import FakeRecorder
from jarvis.voice.setup import run_setup
from jarvis.voice.stt import FakeSTT
from jarvis.voice.tts import FakeTTS, SpeechOutput
from jarvis.voice.wakeword import FakeWakeWord

MAIN = RouteDecision("main_chat", "fake", "fake-1", "medium", "test")
SR = 16000


def tone(ms=400, amp=8000):
    n = SR * ms // 1000
    return Audio(array("h", (int(amp * math.sin(2 * math.pi * 440 * i / SR)) for i in range(n))).tobytes())


@pytest.fixture
def env(tmp_path):
    store = Store(tmp_path / "data" / "jarvis.db")
    yield tmp_path, store
    store.close()


def _session(env, script=None, approver=None):
    home, store = env
    audit = AuditLog(home / "data" / "audit.jsonl")
    return ChatSession(load_config(), FakeProvider(script=script), MAIN, store, audit,
                       now=lambda: datetime(2026, 10, 10, 19, 30), home=home, memory=MemoryStore(home, store),
                       approver=approver, web=WebClient(transport=lambda *a: (404, b""), check_url=lambda u: None),
                       system=SystemTools(apps={}, runner=lambda a: None, opener=lambda u: True))


def _loop(env, session, stt, tts=None, recorder=None, inp="", cfg=None, cloud=None, wakeword=None):
    home, _ = env
    tts = tts or FakeTTS("local")
    speech = SpeechOutput(tts, cloud, "P1", session.audit)
    loop = VoiceLoop(session, stt, speech, recorder or FakeRecorder(), session.audit, session.stop,
                     cfg or load_voice_config(), io.StringIO(), io.StringIO(inp), home, wakeword=wakeword)
    return loop, tts


def _audit(home):
    return [json.loads(l) for l in (home / "data" / "audit.jsonl").read_text(encoding="utf-8").splitlines()]


# ---- one turn, end to end ----

def test_voice_turn_end_to_end(env):
    home, _ = env
    session = _session(env)
    stt = FakeSTT([Transcript("Good evening Jarvis", "en", 0.93)])
    loop, tts = _loop(env, session, stt)
    result = loop.handle_audio(tone())
    assert result.status == "replied" and result.reply == "Good evening, sir."
    assert tts.spoken == [("Good evening, sir.", "en")]
    assert stt.calls[0][0].pcm == tone().pcm and stt.calls[0][1] is None
    turn = [e for e in _audit(home) if e["event"] == "voice_turn"][0]
    assert turn["status"] == "replied" and turn["source"] == "voice" and turn["stt_engine"] == "fake"
    assert turn["tts_engine"] == "local" and turn["cloud_tts"] is False and turn["audio_stored"] is False
    raw = (home / "data" / "audit.jsonl").read_text(encoding="utf-8")
    assert "Good evening Jarvis" not in raw  # lengths only, not the words
    assert not (home / "data" / "voice").exists()  # no audio kept by default


def test_audio_is_stored_only_when_configured(env):
    home, _ = env
    cfg = load_voice_config()
    cfg["store_audio"] = True
    loop, _ = _loop(env, _session(env), FakeSTT(["hello"]), cfg=cfg)
    loop.handle_audio(tone())
    assert len(list((home / "data" / "voice" / "recordings").glob("*.wav"))) == 1


def test_unclear_speech_is_not_sent(env):
    session = _session(env)
    loop, tts = _loop(env, session, FakeSTT([Transcript("delete everything", "en", 0.2)]))
    assert loop.handle_audio(tone()).status == "unclear"
    assert session.provider.requests == [] and tts.spoken == [(REPEAT, "en")]
    assert loop.handle_audio(Audio(b"")).status == "no_audio"


def test_voice_style_is_added_to_the_system_prompt(env):
    session = _session(env)
    session.context = VoiceStyleContext(session.context, voice_style())
    loop, _ = _loop(env, session, FakeSTT(["hello"]))
    loop.handle_audio(tone())
    assert "Voice mode" in session.provider.requests[0].system


def test_marathi_reply_uses_cloud_only_when_enabled(env):
    reply = "नमस्कार, उद्याची बैठक दहा वाजता आहे."
    cloud = FakeTTS("edge_tts", cloud=True)
    loop, local = _loop(env, _session(env, [reply]), FakeSTT(["meeting kadhi aahe"]), cloud=cloud)
    r = loop.handle_audio(tone())
    assert r.cloud_tts and cloud.spoken == [(reply, "mr")] and local.spoken == []


def test_p3_reply_never_goes_to_cloud_voice(env):
    reply = "तुमचा पासवर्ड आहे hunter22"
    cloud = FakeTTS("edge_tts", cloud=True)
    loop, local = _loop(env, _session(env, [reply]), FakeSTT(["password sang"]), cloud=cloud)
    r = loop.handle_audio(tone())
    assert not r.cloud_tts and cloud.spoken == [] and "hunter22" not in local.spoken[0][0]


# ---- emergency stop ----

def test_emergency_stop_blocks_the_turn(env):
    session = _session(env)
    session.stop.engage("test")
    loop, tts = _loop(env, session, FakeSTT(["hello"]))
    assert loop.handle_audio(tone()).status == "emergency_stop"
    assert session.provider.requests == [] and tts.spoken == []


def test_saying_emergency_stop_engages_the_switch(env):
    session = _session(env)
    loop, tts = _loop(env, session, FakeSTT(["Emergency stop!"]))
    assert loop.handle_audio(tone()).status == "emergency_stop"
    assert session.stop.engaged() and session.provider.requests == []


def test_saying_stop_only_silences(env):
    session = _session(env)
    tts = FakeTTS("local", keep_playing=True)
    loop, _ = _loop(env, session, FakeSTT(["hello", "stop"]), tts=tts)
    loop.handle_audio(tone())
    assert loop.handle_audio(tone()).status == "stopped_speaking"
    assert tts.playbacks[0].stopped and not session.stop.engaged()


# ---- the loop: push-to-talk, typed input, barge-in by key ----

def test_run_loop_push_to_talk_typed_and_barge_in(env):
    home, _ = env
    session = _session(env, ["First answer.", "Second answer."])
    tts = FakeTTS("local", keep_playing=True)
    rec = FakeRecorder([tone()])
    loop, _ = _loop(env, session, FakeSTT(["what time is it"]), tts=tts, recorder=rec,
                    inp="\nhow are you\n/exit\n")
    assert loop.run() == 0
    assert rec.recorded == 1
    assert [t for t, _ in tts.spoken] == ["First answer.", "Second answer."]
    assert tts.playbacks[0].stopped and tts.playbacks[1].stopped  # Enter interrupted; exit silenced
    events = [e["event"] for e in _audit(home)]
    assert events.count("voice_turn") == 2 and "voice_barge_in" in events


def test_run_loop_refuses_while_stopped(env):
    session = _session(env)
    session.stop.engage("x")
    loop, tts = _loop(env, session, FakeSTT(["hello"]), inp="hello\n/exit\n")
    loop.run()
    assert "Emergency stop is ON" in loop.out.getvalue() and tts.spoken == []


def test_wake_word_mode(env):
    session = _session(env)
    cfg = load_voice_config()
    rec = FakeRecorder([tone()], frames=[b"noise", b"WAKE"])
    ww = FakeWakeWord()
    loop, tts = _loop(env, session, FakeSTT(["hello"]), recorder=rec, cfg=cfg, wakeword=ww)
    calls = {"n": 0}
    real = loop._wait_for_wake_word

    def once():
        calls["n"] += 1
        return real() if calls["n"] == 1 else False

    loop._wait_for_wake_word = once
    assert loop.run() == 0
    assert ww.heard == 2 and tts.spoken == [("Good evening, sir.", "en")]


# ---- approvals by voice: default deny ----

def _req():
    return ApprovalRequest("overwrite_file", "T2", {"path": "a.txt", "content": "new"}, "significant change")


def _approver(env, typed, heard=None, cloud=None):
    home, _ = env
    local = FakeTTS("local")
    speech = SpeechOutput(local, cloud, "P1")
    stt = FakeSTT([heard] if heard is not None else [])
    ask = voice_approver(speech, stt, FakeRecorder([tone()]), io.StringIO(), io.StringIO(typed),
                         AuditLog(home / "data" / "audit.jsonl"))
    return ask, local


@pytest.mark.parametrize("typed,heard,expected", [
    ("y\n", None, True), ("ho\n", None, True), ("हो\n", None, True), ("yes\n", None, True),
    ("n\n", None, False), ("sure\n", None, False), ("", None, False),  # end of input = no
    ("\n", Transcript("Yes.", "en", 0.9), True), ("\n", Transcript("हो", "mr", 0.8), True),
    ("\n", Transcript("yes", "en", 0.2), False),  # not sure what was heard
    ("\n", Transcript("yes but wait", "en", 0.9), False), ("\n", Transcript("no", "en", 0.9), False),
    ("\n", Transcript("", None, 0.0), False), ("\n", None, False),
])
def test_voice_approval_needs_an_explicit_yes(env, typed, heard, expected):
    ask, local = _approver(env, typed, heard)
    assert ask(_req()) is expected
    assert "overwrite file" in local.spoken[0][0]


def test_voice_approval_errors_mean_no(env):
    home, _ = env

    class Broken:
        name = "broken"

        def transcribe(self, audio, language_hint=None):
            raise RuntimeError("no model")

    ask = voice_approver(SpeechOutput(FakeTTS()), Broken(), FakeRecorder([tone()]), io.StringIO(), io.StringIO("\n"))
    assert ask(_req()) is False


def test_approval_request_is_never_spoken_by_cloud_voice(env):
    cloud = FakeTTS("edge_tts", cloud=True)
    ask, local = _approver(env, "n\n", cloud=cloud)
    ask(_req())
    assert cloud.spoken == [] and local.spoken


def test_spoken_yes_matching():
    assert is_explicit_yes(" Yes, please. ") and is_explicit_yes("Ho Jarvis")
    assert not is_explicit_yes("yes delete everything") and not is_explicit_yes("yesterday")


def test_denied_by_voice_blocks_the_tool(env):
    home, _ = env
    (home / "workspace").mkdir(parents=True, exist_ok=True)
    (home / "workspace" / "a.txt").write_text("old", encoding="utf-8")
    speech = SpeechOutput(FakeTTS("local"))
    ask = voice_approver(speech, FakeSTT([Transcript("maybe later", "en", 0.9)]), FakeRecorder([tone()]),
                         io.StringIO(), io.StringIO("\n"))
    session = _session(env, [{"tool": "overwrite_file", "arguments": {"path": "a.txt", "content": "new"}}, "ok"],
                       approver=ask)
    loop, _ = _loop(env, session, FakeSTT(["replace a.txt"]))
    loop.handle_audio(tone())
    assert (home / "workspace" / "a.txt").read_text(encoding="utf-8") == "old"
    rows = sqlite3.connect(home / "data" / "jarvis.db").execute("SELECT decision FROM approvals").fetchall()
    assert rows == [("denied",)]


# ---- setup (downloads only when asked) ----

def test_setup_shows_size_and_asks(tmp_path):
    out = io.StringIO()
    got = []
    assert run_setup(load_voice_config(), tmp_path, out, io.StringIO("n\n"), "small",
                     downloader=lambda m, d: got.append(m), installed=lambda: True) == 1
    assert "486 MB" in out.getvalue() and got == []


def test_setup_downloads_after_yes(tmp_path):
    def fake_download(model, dest):
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "model.bin").write_bytes(b"x")

    out = io.StringIO()
    assert run_setup(load_voice_config(), tmp_path, out, io.StringIO("ho\n"), "base",
                     downloader=fake_download, installed=lambda: True) == 0
    assert (tmp_path / "data" / "models" / "whisper" / "base" / "model.bin").exists()
    assert run_setup(load_voice_config(), tmp_path, out, io.StringIO(""), "base", installed=lambda: True) == 0
    assert "already downloaded" in out.getvalue()


def test_setup_refuses_unknown_model_and_missing_package(tmp_path):
    out = io.StringIO()
    assert run_setup(load_voice_config(), tmp_path, out, io.StringIO(), "giant") == 2
    assert run_setup(load_voice_config(), tmp_path, out, io.StringIO(), "small", installed=lambda: False) == 1
    assert "pip install faster-whisper" in out.getvalue()


# ---- CLI ----

def test_cli_register_and_say(isolated):
    import argparse

    p = argparse.ArgumentParser()
    cli_voice.register(p.add_subparsers(dest="command"))
    args = p.parse_args(["say", "Good", "evening,", "sir."])
    tts = FakeTTS("local")
    out = io.StringIO()
    assert cli_voice.cmd_say(args, out, speech=SpeechOutput(tts)) == 0
    assert tts.spoken == [("Good evening, sir.", "en")] and "Speaking with local" in out.getvalue()
    assert p.parse_args(["voice"]).action == "run"


def test_cli_say_respects_emergency_stop(isolated):
    StopSwitch(isolated / "data").engage("x")
    out = io.StringIO()
    assert cli_voice.main(["say", "hello"], out=out) == 1
    assert "Emergency stop" in out.getvalue()


def test_cli_voice_session_with_fakes(isolated):
    out = io.StringIO()
    args = SimpleNamespace(action="run", provider="fake", model=None, yes=False)
    tts = FakeTTS("local")
    code = cli_voice.cmd_voice(args, out, io.StringIO("\nhello\n/exit\n"), stt=FakeSTT(["good evening"]),
                               speech=SpeechOutput(tts), recorder=FakeRecorder([tone()]))
    assert code == 0
    assert [t for t, _ in tts.spoken] == ["Good evening, sir.", "Good evening, sir."]
    events = [json.loads(l)["event"] for l in (isolated / "data" / "audit.jsonl").read_text(encoding="utf-8").splitlines()]
    assert "voice_session" in events and events.count("voice_turn") == 2
