"""Phase 6 voice engines: audio helpers, STT mapping, TTS command building, privacy routing, recorder."""

import ast
import math
import subprocess
from array import array
from pathlib import Path
from types import SimpleNamespace

import pytest

from jarvis.control.audit import AuditLog
from jarvis.control.stop import StopSwitch
from jarvis.voice import stt as stt_mod
from jarvis.voice.base import Audio, Transcript, VoiceUnavailable, rms
from jarvis.voice.config import DEFAULTS, load_voice_config
from jarvis.voice.recorder import FakeRecorder, FakeSoundDevice, SoundDeviceRecorder, list_devices
from jarvis.voice.stt import FakeSTT, FasterWhisperSTT, language_hint, make_stt, transcript_from_segments
from jarvis.voice.tts import (
    EdgeTTS,
    FakePlayback,
    FakeTTS,
    MacSayTTS,
    ProcessPlayback,
    SpeechOutput,
    WindowsSapiTTS,
    detect_language,
    local_engine_name,
    make_local_tts,
    make_speech,
    play_file_command,
    spoken_text,
)
from jarvis.voice.vad import EnergyVAD, PlaybackGuard
from jarvis.voice.wakeword import FakeWakeWord, OpenWakeWordDetector, make_wakeword

VOICE_PKG = Path(__file__).resolve().parent.parent / "jarvis" / "voice"
SR = 16000


def tone(ms: int, freq: float = 440.0, amp: int = 8000) -> bytes:
    n = SR * ms // 1000
    return array("h", (int(amp * math.sin(2 * math.pi * freq * i / SR)) for i in range(n))).tobytes()


def silence(ms: int) -> bytes:
    return bytes(SR * ms // 1000 * 2)


# ---- audio and VAD ----

def test_audio_wav_round_trip_and_levels():
    a = Audio(tone(200) + silence(100))
    assert abs(a.seconds - 0.3) < 1e-6
    assert Audio.from_wav(a.to_wav()) == a
    assert rms(silence(80)) == 0.0
    assert rms(tone(80)) > 5000


def test_energy_vad_needs_sustained_speech():
    vad = EnergyVAD(threshold_rms=900, min_speech_ms=240)
    assert not vad.feed(tone(80)) and not vad.feed(tone(80))
    assert vad.feed(tone(80))  # 240 ms of speech
    vad.reset()
    assert not vad.feed(tone(80)) and not vad.feed(silence(80)) and not vad.feed(tone(80))


# ---- speech-to-text ----

def _seg(text, logprob=-0.1, no_speech=0.01):
    return SimpleNamespace(text=text, avg_logprob=logprob, no_speech_prob=no_speech)


def test_whisper_scores_map_to_confidence():
    t = transcript_from_segments([_seg(" Hello"), _seg(" Jarvis.", -0.2)], "en", 0.98)
    assert t.text == "Hello Jarvis." and t.language == "en"
    assert 0.8 < t.confidence < 0.95
    assert transcript_from_segments([_seg(" thanks", no_speech=0.9)], "en", 0.9) == Transcript("", "en", 0.0)
    unsure = transcript_from_segments([_seg(" ho")], "mr", 0.2)
    assert unsure.confidence < 0.5


def test_whisper_engine_says_how_to_set_up(monkeypatch, tmp_path):
    engine = FasterWhisperSTT(tmp_path, "small")
    monkeypatch.setattr(stt_mod, "faster_whisper_installed", lambda: False)
    with pytest.raises(VoiceUnavailable, match="pip install faster-whisper"):
        engine.transcribe(Audio(tone(100)))
    monkeypatch.setattr(stt_mod, "faster_whisper_installed", lambda: True)
    with pytest.raises(VoiceUnavailable, match=r"jarvis voice setup.*486 MB"):
        engine.check()


def test_stt_selection_and_hints(tmp_path):
    assert isinstance(make_stt({"stt": {"engine": "faster_whisper", "model": "base"}}, tmp_path), FasterWhisperSTT)
    assert isinstance(make_stt({"stt": {"engine": "fake"}}, tmp_path), FakeSTT)
    with pytest.raises(ValueError):
        make_stt({"stt": {"engine": "nope"}}, tmp_path)
    assert language_hint({"stt": {"language": "auto"}}) is None
    assert language_hint({"stt": {"language": "mr"}}) == "mr"


def test_default_config_is_safe():
    cfg = load_voice_config()
    assert cfg["tts"]["marathi"]["cloud_enabled"] is False
    assert cfg["wake_word"]["enabled"] is False
    assert cfg["store_audio"] is False
    assert cfg["stt"]["model"] in stt_mod.WHISPER_MODELS
    assert set(DEFAULTS) <= set(cfg)


# ---- text-to-speech commands (no shell, no injection) ----

class Recorded:
    def __init__(self):
        self.calls = []

    def __call__(self, argv, **kw):
        self.calls.append((argv, kw))
        return SimpleNamespace(stdin=SimpleNamespace(write=lambda b: kw.setdefault("_stdin", b), close=lambda: None),
                               poll=lambda: None, wait=lambda timeout=None: 0, terminate=lambda: None, kill=lambda: None)


EVIL = "'; Remove-Item -Recurse C:\\ ; \" $(rm -rf ~) `calc`"


def test_windows_tts_passes_text_through_environment():
    popen = Recorded()
    WindowsSapiTTS("Microsoft Zira Desktop", rate=3, popen=popen).speak(EVIL)
    argv, kw = popen.calls[0]
    assert argv[0] == "powershell" and isinstance(argv, list)
    assert kw["shell"] is False
    assert all(EVIL not in a and "Remove-Item" not in a for a in argv)
    assert kw["env"]["JARVIS_TTS_TEXT"] == EVIL
    assert kw["env"]["JARVIS_TTS_VOICE"] == "Microsoft Zira Desktop" and kw["env"]["JARVIS_TTS_RATE"] == "3"


def test_mac_say_passes_text_through_stdin():
    popen = Recorded()
    MacSayTTS("Rishi", rate=180, popen=popen).speak("-v Alex " + EVIL)
    argv, kw = popen.calls[0]
    assert argv == ["say", "-v", "Rishi", "-r", "180"]
    assert kw["shell"] is False and kw["stdin"] == subprocess.PIPE
    assert kw["_stdin"] == ("-v Alex " + EVIL).encode("utf-8")
    assert MacSayTTS(popen=popen).command() == ["say"]


def test_empty_text_starts_nothing():
    popen = Recorded()
    assert WindowsSapiTTS(popen=popen).speak("   ").wait() is True
    assert popen.calls == []


def test_no_shell_true_in_voice_code():
    for path in list(VOICE_PKG.rglob("*.py")) + [VOICE_PKG.parent / "cli_voice.py"]:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.keyword) and node.arg == "shell":
                assert isinstance(node.value, ast.Constant) and node.value.value is False, path


@pytest.mark.parametrize("platform,expected", [("win32", "windows_sapi"), ("darwin", "mac_say"), ("linux", None)])
def test_engine_selection_per_platform(platform, expected):
    assert local_engine_name({"tts": {"engine": "auto"}}, platform) == expected
    engine = make_local_tts({"tts": {"engine": "auto", "voice": "", "rate": 0}}, platform, Recorded())
    assert (engine.name if engine else None) == expected


def test_engine_selection_by_config():
    assert local_engine_name({"tts": {"engine": "mac_say"}}, "win32") == "mac_say"
    with pytest.raises(ValueError):
        make_local_tts({"tts": {"engine": "nope"}}, "win32")


def test_file_playback_commands(tmp_path):
    argv, env = play_file_command(tmp_path / "a.mp3", "darwin")
    assert argv == ["afplay", str(tmp_path / "a.mp3")] and env is None
    argv, env = play_file_command(tmp_path / "a.mp3", "win32")
    assert argv[0] == "powershell" and env["JARVIS_AUDIO_FILE"] == str(tmp_path / "a.mp3")
    assert all(str(tmp_path) not in a for a in argv)
    with pytest.raises(VoiceUnavailable):
        play_file_command(tmp_path / "a.mp3", "linux")


class FakeProc:
    def __init__(self):
        self.running = True
        self.terminated = False

    def poll(self):
        return None if self.running else 0

    def wait(self, timeout=None):
        if self.running and timeout is not None:
            raise subprocess.TimeoutExpired("x", timeout)
        return 0

    def terminate(self):
        self.terminated = True
        self.running = False

    def kill(self):
        self.running = False


def test_process_playback_stop_and_cleanup(tmp_path):
    f = tmp_path / "x.mp3"
    f.write_bytes(b"x")
    proc = FakeProc()
    pb = ProcessPlayback(proc, cleanup=lambda: f.unlink())
    assert pb.is_playing() and pb.wait(timeout=0.01) is False
    pb.stop()
    pb.stop()  # safe twice
    assert proc.terminated and not pb.is_playing() and not f.exists()


def test_edge_tts_synthesizes_plays_and_cleans_up(tmp_path):
    made = []

    def synth(text, voice, path):
        made.append((text, voice, path))
        path.write_bytes(b"mp3")

    popen = Recorded()
    pb = EdgeTTS("mr-IN-ManoharNeural", tmp_path / "tmp", popen, synthesize=synth, platform="darwin").speak("नमस्कार")
    text, voice, path = made[0]
    assert (text, voice) == ("नमस्कार", "mr-IN-ManoharNeural") and path.exists()
    assert popen.calls[0][0] == ["afplay", str(path)]
    pb.wait()
    assert not path.exists()


# ---- what is spoken and where it goes (privacy) ----

MARATHI = "उद्या सकाळी दहा वाजता बैठक आहे."


def _speech(cloud_raises=False, max_privacy="P1", audit=None):
    local, cloud = FakeTTS("local"), FakeTTS("edge_tts", cloud=True)
    if cloud_raises:
        def boom(text, language="mr"):
            raise ConnectionError("offline")
        cloud.speak = boom
    return SpeechOutput(local, cloud, max_privacy, audit), local, cloud


def test_language_detection_and_spoken_text():
    assert detect_language(MARATHI) == "mr"
    assert detect_language("Good evening, sir.") == "en"
    assert detect_language("The meeting is at 10, बैठक") == "en"
    said = spoken_text("**Done.** Your password: hunter22 is [here](http://x.test).")
    assert "hunter22" not in said and "withheld" in said and "*" not in said and "http" not in said


def test_marathi_p1_goes_to_cloud_when_enabled():
    speech, local, cloud = _speech()
    res = speech.speak(MARATHI)
    assert res.cloud and res.engine == "edge_tts" and cloud.spoken == [(MARATHI, "mr")] and local.spoken == []


def test_p3_text_never_reaches_cloud_voice(tmp_path):
    audit = AuditLog(tmp_path / "audit.jsonl")
    speech, local, cloud = _speech(audit=audit)
    for secret in ("माझा पासवर्ड आहे hunter22 लक्षात ठेवा", "otp 482913 आहे, कोणालाही सांगू नका",
                   "कार्ड 4111 1111 1111 1111 वापरा"):
        res = speech.speak(secret, language="mr")
        assert not res.cloud
    assert cloud.spoken == []
    assert all("hunter22" not in t and "482913" not in t and "4111" not in t for t, _ in local.spoken)
    assert "P3" in (tmp_path / "audit.jsonl").read_text(encoding="utf-8")


def test_sensitive_and_english_text_stay_local():
    speech, local, cloud = _speech()
    assert not speech.speak(MARATHI, sensitivity="P2").cloud
    assert not speech.speak(MARATHI, sensitivity="P3").cloud
    assert not speech.speak(MARATHI, sensitivity="bogus").cloud
    assert not speech.speak("Good evening, sir.").cloud
    assert cloud.spoken == [] and len(local.spoken) == 4


def test_cloud_privacy_cap_cannot_be_raised():
    speech, _, cloud = _speech(max_privacy="P3")
    assert speech.cloud_max_privacy == "P1"
    assert not speech.speak(MARATHI, sensitivity="P2").cloud and cloud.spoken == []


def test_cloud_failure_falls_back_to_local():
    speech, local, _ = _speech(cloud_raises=True)
    res = speech.speak(MARATHI)
    assert not res.cloud and res.engine == "local" and "failed" in res.note and local.spoken


def test_cloud_voice_is_off_by_default(tmp_path):
    speech = make_speech(load_voice_config(), tmp_path, platform="win32", popen=Recorded())
    assert speech.cloud_marathi is None
    assert speech.speak(MARATHI).engine == "windows_sapi"
    on = make_speech(load_voice_config(), tmp_path, platform="win32", popen=Recorded(), force_cloud=True)
    assert on.cloud_marathi is not None and on.cloud_marathi.cloud


def test_no_local_voice_is_reported():
    with pytest.raises(VoiceUnavailable):
        SpeechOutput(None).speak("hello")


# ---- recording with a fake device ----

def test_push_to_talk_records_until_stop():
    frames = [tone(80), tone(80), silence(80)]
    sd = FakeSoundDevice(frames)
    stopped = []
    rec = SoundDeviceRecorder(lambda: stopped.append(True), sd=sd)
    audio = rec.record_push_to_talk()
    assert stopped == [True] and audio.pcm == b"".join(frames) and audio.sample_rate == SR
    opened = sd.opened[0]
    assert opened["samplerate"] == SR and opened["channels"] == 1 and opened["dtype"] == "int16"
    assert opened["blocksize"] == 1280


def test_push_to_talk_caps_length():
    rec = SoundDeviceRecorder(lambda: None, max_seconds=0.1, sd=FakeSoundDevice([tone(80)] * 5))
    assert rec.record_push_to_talk().seconds == pytest.approx(0.1)


def test_utterance_ends_after_silence():
    frames = [silence(80), tone(80), tone(80)] + [silence(80)] * 12 + [tone(80)] * 3
    rec = SoundDeviceRecorder(lambda: None, sd=FakeSoundDevice(frames))
    audio = rec.record_utterance(EnergyVAD().is_speech, end_silence_ms=400, max_seconds=0.5)
    assert audio.seconds == pytest.approx(0.08 * 8)  # 1 silence + 2 speech + 5 silence frames


def test_list_devices_with_fake_module():
    sd = FakeSoundDevice([], devices=[{"name": "Demo Mic", "max_input_channels": 1, "max_output_channels": 0}])
    assert list_devices(sd) == [{"index": 0, "name": "Demo Mic", "inputs": 1, "outputs": 0}]


# ---- barge-in, emergency stop during speech, wake word ----

def test_guard_stops_speech_on_emergency_stop(tmp_path):
    switch = StopSwitch(tmp_path)
    pb = FakePlayback(playing=True)
    guard = PlaybackGuard(pb, switch, poll_seconds=0.01).start()
    switch.engage("test")
    guard._threads[0].join(2)
    assert pb.stopped and guard.emergency
    guard.close()


def test_guard_stops_speech_when_user_talks(tmp_path):
    pb = FakePlayback(playing=True)
    rec = FakeRecorder(frames=[silence(80), tone(80), tone(80), tone(80), tone(80)])
    guard = PlaybackGuard(pb, StopSwitch(tmp_path), rec, EnergyVAD(min_speech_ms=240), poll_seconds=0.01).start()
    guard._threads[1].join(2)
    assert pb.stopped and guard.barged_in
    guard.close()


def test_guard_ignores_quiet_room(tmp_path):
    pb = FakePlayback(playing=True)
    rec = FakeRecorder(frames=[silence(80)] * 10)
    guard = PlaybackGuard(pb, StopSwitch(tmp_path), rec, EnergyVAD(), poll_seconds=0.01).start()
    guard._threads[1].join(2)
    assert not pb.stopped and not guard.barged_in
    guard.close()


def test_wake_word_off_by_default_and_lazy():
    assert make_wakeword(load_voice_config()) is None
    det = make_wakeword({"wake_word": {"enabled": True, "engine": "openwakeword", "model": "hey_jarvis"}})
    assert isinstance(det, OpenWakeWordDetector) and det._model is None  # nothing loaded yet
    fake = FakeWakeWord()
    assert not fake.process(b"noise") and fake.process(b"WAKE")


def test_openwakeword_adapter_with_fake_model():
    pytest.importorskip("numpy")
    calls = []

    class Model:
        def __init__(self, wakeword_models, inference_framework):
            calls.append((wakeword_models, inference_framework))

        def predict(self, x):
            return {"hey_jarvis": 0.9 if x.max() > 1000 else 0.01}

    det = OpenWakeWordDetector("hey_jarvis", 0.5, factory=Model)
    assert not det.process(silence(80)) and det.process(tone(80))
    assert calls == [(["hey_jarvis"], "onnx")]
