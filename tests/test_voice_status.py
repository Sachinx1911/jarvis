"""Voice status for the terminal (`jarvis voice devices`) and the dashboard (GET /api/voice/status).

Offline and with fakes: package checks are replaced, "models" are empty files in a temporary
JARVIS_HOME, and anything that would load a model or download fails the test.
"""

import argparse
import copy
import io

import pytest
from fastapi.testclient import TestClient  # fastapi is a core dependency (the dashboard)

from jarvis import cli_voice
from jarvis.core.runtime import make_chat
from jarvis.voice import mms_tts as mms_mod
from jarvis.voice import models as models_mod
from jarvis.voice import status as status_mod
from jarvis.voice import stt as stt_mod
from jarvis.voice.config import DEFAULTS
from jarvis.voice.models import HEY_JARVIS, INDICCONFORMER_MR, MMS_TTS_MAR, VOICE_MODELS
from jarvis.voice.recorder import FakeSoundDevice
from jarvis.voice.status import status_lines, voice_status
from jarvis.voice.stt import WHISPER_MODELS
from jarvis.voice.tts import FakeTTS
from jarvis.web.app import create_app
from jarvis.web.settings import WebSettings

ALL = {"faster-whisper": True, "onnx-asr": True, "onnxruntime": True, "openwakeword": True}
NONE = {name: False for name in ALL}
PARTS = ("english_stt", "marathi_stt", "local_voice", "offline_marathi_voice", "cloud_marathi_voice", "wake_word")


def cfg(**changes):
    """The default voice config with nested changes, e.g. cfg(stt={"language": "mr"})."""
    c = copy.deepcopy(DEFAULTS)
    for key, value in changes.items():
        if isinstance(value, dict):
            for k, v in value.items():
                if isinstance(v, dict):
                    c[key][k].update(v)
                else:
                    c[key][k] = v
        else:
            c[key] = value
    return c


def put_models(home, whisper="small", marathi=True, voice=True, wake=True):
    """Empty stand-in files where the real models would be (presence is all status checks)."""
    if whisper:
        (stt_mod.model_path(home, whisper)).mkdir(parents=True, exist_ok=True)
        (stt_mod.model_path(home, whisper) / "model.bin").write_bytes(b"")
    for on, m in ((marathi, INDICCONFORMER_MR), (voice, MMS_TTS_MAR), (wake, HEY_JARVIS)):
        if on:
            m.path(home).mkdir(parents=True, exist_ok=True)
            (m.path(home) / m.ready_file).write_bytes(b"")


@pytest.fixture(autouse=True)
def nothing_loads_or_downloads(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("status must not load a model or download anything")

    monkeypatch.setattr(stt_mod, "_load_onnx_asr", boom)
    monkeypatch.setattr(mms_mod, "_session", boom)
    monkeypatch.setattr(models_mod, "download", boom)
    monkeypatch.setattr(models_mod, "_hf_fetch", boom)


# ---- the status itself ----

def test_fresh_machine_says_what_to_run(tmp_path):
    s = voice_status(cfg(), tmp_path, packages=ALL, platform="darwin")
    assert s["stt_language"] == "auto" and "Marathi engine" in s["stt_language_detail"]
    en, mr, offline = s["english_stt"], s["marathi_stt"], s["offline_marathi_voice"]
    assert en["engine"] == "faster_whisper" and en["model"] == "small" and en["model_mb"] == WHISPER_MODELS["small"][1]
    assert en["package_installed"] is True and en["model_present"] is False and en["ready"] is False
    assert en["setup"] == "jarvis voice setup --model small" and "not downloaded" in en["detail"]
    assert mr["engine"] == "indicconformer" and mr["enabled"] is True and mr["ready"] is False
    assert mr["package"] == "onnx-asr" and mr["package_installed"] is True and mr["model_present"] is False
    assert mr["setup"] == "jarvis voice setup --model indicconformer-mr" and "not downloaded" in mr["detail"]
    assert offline["engine"] == "mms_tts" and offline["package"] == "onnxruntime" and offline["ready"] is False
    assert offline["setup"] == "jarvis voice setup --model mms-tts-mar"
    assert s["local_voice"] == {"engine": "mac_say", "ready": True, "detail": "ready"}
    assert s["cloud_marathi_voice"]["enabled"] is False and s["cloud_marathi_voice"]["max_privacy"] == "P1"
    ww = s["wake_word"]
    assert ww["enabled"] is False and ww["model_present"] is False and ww["setup"] == "jarvis voice setup --model hey_jarvis"
    assert s["setup_needed"] is True and s["setup_command"] == "jarvis voice setup"


def test_everything_downloaded_is_ready(tmp_path):
    put_models(tmp_path)
    s = voice_status(cfg(wake_word={"enabled": True}), tmp_path, packages=ALL, platform="win32")
    for part in ("english_stt", "marathi_stt", "offline_marathi_voice", "wake_word"):
        assert s[part]["ready"] is True and s[part]["detail"] == "ready", part
        assert s[part]["model_present"] is True and s[part]["package_installed"] is True, part
    assert s["local_voice"]["engine"] == "windows_sapi"
    assert s["setup_needed"] is False


def test_missing_packages_are_named_with_the_install_command(tmp_path):
    put_models(tmp_path)
    s = voice_status(cfg(wake_word={"enabled": True}), tmp_path, packages=NONE, platform="linux")
    assert s["english_stt"]["ready"] is False and "faster-whisper is not installed" in s["english_stt"]["detail"]
    assert s["marathi_stt"]["ready"] is False and "onnx-asr is not installed" in s["marathi_stt"]["detail"]
    assert s["offline_marathi_voice"]["ready"] is False and "onnxruntime" in s["offline_marathi_voice"]["detail"]
    assert s["wake_word"]["ready"] is False and "openWakeWord is not installed" in s["wake_word"]["detail"]
    for part in ("english_stt", "marathi_stt", "offline_marathi_voice"):
        assert s[part]["install_hint"] == 'pip install -e ".[voice]"'
    assert s["wake_word"]["install_hint"] == 'pip install -e ".[wakeword]"'
    assert s["local_voice"]["engine"] is None and "none on this platform" in s["local_voice"]["detail"]
    assert s["setup_needed"] is True


def test_engines_switched_off_are_not_missing(tmp_path):
    put_models(tmp_path, marathi=False, voice=False, wake=False)
    c = cfg(stt={"marathi_engine": "none"}, tts={"marathi": {"offline_engine": "none"}})
    s = voice_status(c, tmp_path, packages=ALL, platform="darwin")
    assert s["marathi_stt"]["enabled"] is False and s["marathi_stt"]["engine"] == "none"
    assert s["marathi_stt"]["detail"].startswith("off")
    assert s["offline_marathi_voice"]["enabled"] is False and s["offline_marathi_voice"]["detail"].startswith("off")
    assert "Whisper handles every language" in s["stt_language_detail"]
    assert s["setup_needed"] is False  # Whisper is ready; nothing that is on is missing


@pytest.mark.parametrize("mode,marathi,words", [
    ("en", "indicconformer", "English only"),
    ("mr", "indicconformer", "Marathi only (indicconformer)"),
    ("mr", "none", "Marathi only, with Whisper"),
    ("auto", "indicconformer", "English goes to Whisper"),
    ("hindi", "indicconformer", "unknown mode"),
])
def test_language_mode_in_plain_words(tmp_path, mode, marathi, words):
    s = voice_status(cfg(stt={"language": mode, "marathi_engine": marathi}), tmp_path, packages=ALL)
    assert s["stt_language"] == mode and words in s["stt_language_detail"]


def test_cloud_voice_on_is_shown_and_capped_at_p1(tmp_path):
    s = voice_status(cfg(tts={"marathi": {"cloud_enabled": True, "max_privacy": "P3"}}), tmp_path, packages=ALL)
    cloud = s["cloud_marathi_voice"]
    assert cloud["enabled"] is True and cloud["engine"] == "edge_tts" and cloud["voice"] == "mr-IN-ManoharNeural"
    assert cloud["max_privacy"] == "P1" and "P3 never" in cloud["detail"]


def test_unknown_engines_are_reported_not_raised(tmp_path):
    c = cfg(stt={"engine": "nope", "marathi_engine": "other"}, tts={"marathi": {"offline_engine": "x"}},
            wake_word={"engine": "porcupine", "enabled": True})
    s = voice_status(c, tmp_path, packages=ALL)
    assert "unknown speech-to-text engine" in s["english_stt"]["detail"]
    assert "unknown Marathi speech-to-text engine" in s["marathi_stt"]["detail"]
    assert "unknown offline Marathi voice" in s["offline_marathi_voice"]["detail"]
    assert "unknown wake-word engine" in s["wake_word"]["detail"]
    assert all(not s[p]["ready"] for p in ("english_stt", "marathi_stt", "offline_marathi_voice", "wake_word"))


def test_each_package_is_checked_at_most_once(tmp_path):
    calls = []

    def check(name):
        def run():
            calls.append(name)
            return True
        return run

    voice_status(cfg(), tmp_path, packages={n: check(n) for n in ALL})
    assert sorted(calls) == sorted(set(calls)) and "onnx-asr" in calls


def test_terminal_lines(tmp_path):
    put_models(tmp_path, marathi=False)
    text = "\n".join(status_lines(voice_status(cfg(), tmp_path, packages=ALL, platform="darwin")))
    assert "Speech-to-text language: auto" in text
    assert "English speech-to-text: Whisper 'small' (486 MB): faster-whisper installed, model downloaded: ready" in text
    assert ("Marathi speech-to-text: IndicConformer (indicconformer-mr, 138 MB): onnx-asr installed, "
            "model NOT downloaded: NOT ready: run `jarvis voice setup --model indicconformer-mr`") in text
    assert "Voice (text-to-speech): mac_say" in text
    assert "Offline Marathi voice: MMS-TTS (mms-tts-mar, 115 MB): onnxruntime installed, model downloaded: ready" in text
    assert "Marathi cloud voice (edge_tts, mr-IN-ManoharNeural): off" in text
    assert "Wake word: off (openwakeword hey_jarvis)" in text
    assert "Something is missing: run `jarvis voice setup`" in text


def test_terminal_lines_name_a_missing_package_first(tmp_path):
    text = "\n".join(status_lines(voice_status(cfg(), tmp_path, packages=NONE)))
    assert "install onnx-asr first: pip install onnx-asr" in text
    assert "install faster-whisper first: pip install faster-whisper" in text


# ---- CLI ----

def test_cli_devices_prints_every_voice_part(tmp_path):
    put_models(tmp_path, whisper=None, voice=False)
    sd = FakeSoundDevice([], devices=[{"name": "Demo Mic", "max_input_channels": 1, "max_output_channels": 0},
                                      {"name": "Demo Speaker", "max_input_channels": 0, "max_output_channels": 2}])
    out = io.StringIO()
    assert cli_voice.cmd_devices(out, sd=sd, cfg=cfg(), home=tmp_path, tts=FakeTTS(), packages=ALL) == 0
    text = out.getvalue()
    assert "Microphones:\n  [0] Demo Mic" in text and "Speakers:\n  [1] Demo Speaker" in text
    assert "English speech-to-text: Whisper 'small'" in text and "run `jarvis voice setup --model small`" in text
    assert "Marathi speech-to-text: IndicConformer (indicconformer-mr, 138 MB)" in text
    assert "onnx-asr installed, model downloaded: ready" in text
    assert "Offline Marathi voice: MMS-TTS" in text and "jarvis voice setup --model mms-tts-mar" in text
    assert "Marathi cloud voice" in text and "Wake word: off" in text
    assert "Speech-to-text language: auto" in text


def test_cli_devices_lists_system_voices_after_the_status(tmp_path):
    class Voices(FakeTTS):
        def voices(self):
            return ["Demo Voice"]

    out = io.StringIO()
    cli_voice.cmd_devices(out, sd=FakeSoundDevice([]), cfg=cfg(), home=tmp_path, tts=Voices(), packages=ALL)
    text = out.getvalue()
    assert text.index("Wake word:") < text.index("System voices") < text.index("  Demo Voice")


def test_cli_model_help_lists_whisper_sizes_and_voice_models():
    p = argparse.ArgumentParser(prog="jarvis")
    sub = p.add_subparsers(dest="command")
    cli_voice.register(sub)
    voice = sub.choices["voice"]
    model = next(a for a in voice._actions if a.dest == "model")
    flat = "".join(voice.format_help().split())  # argparse may wrap lines at hyphens
    for name in list(WHISPER_MODELS) + list(VOICE_MODELS):
        assert name in model.help
        assert name in flat
    assert voice.parse_args(["setup", "--model", "indicconformer-mr"]).model == "indicconformer-mr"


# ---- dashboard API ----

TOKEN = "test-token-not-real"
H = {"X-Jarvis-Token": TOKEN}


def _client(cfgdir, **kw) -> TestClient:
    settings = WebSettings(approval_timeout_s=5, provider="fake")
    app = create_app(settings, TOKEN, chat_factory=lambda rt, approver: make_chat(rt, "fake", approver),
                     allowed_hosts=["testserver"], trusted_clients={"testclient"}, static_dir=None,
                     config_dir=cfgdir, **kw)
    return TestClient(app)


@pytest.fixture
def cfgdir(tmp_path):
    d = tmp_path / "cfg"
    d.mkdir()
    return d


@pytest.fixture
def fake_packages(monkeypatch):
    state = dict(ALL)
    monkeypatch.setattr(status_mod, "package_checks", lambda: {n: (lambda n=n: state[n]) for n in state})
    return state


def test_api_status_keeps_old_fields_and_adds_every_part(isolated, cfgdir, fake_packages):
    from jarvis.voice.stt import FakeSTT

    with _client(cfgdir, stt_factory=lambda: FakeSTT()) as c:
        r = c.get("/api/voice/status", headers=H)
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["stt_ready"] is True and s["stt_detail"] == "ready" and "tts_engine" in s  # unchanged fields
    for part in PARTS:
        assert part in s, part
    assert s["stt_language"] == "auto"
    assert s["english_stt"]["ready"] is False and s["english_stt"]["setup"] == "jarvis voice setup --model small"
    assert s["marathi_stt"]["engine"] == "indicconformer" and s["marathi_stt"]["package_installed"] is True
    assert s["marathi_stt"]["model_present"] is False and s["marathi_stt"]["ready"] is False
    assert s["offline_marathi_voice"]["engine"] == "mms_tts" and s["offline_marathi_voice"]["model_present"] is False
    assert s["cloud_marathi_voice"]["enabled"] is False
    assert s["wake_word"]["enabled"] is False and s["wake_word"]["model_present"] is False
    assert s["setup_needed"] is True and s["setup_command"] == "jarvis voice setup"


def test_api_status_ready_when_models_are_present(isolated, cfgdir, fake_packages):
    from jarvis.voice.stt import FakeSTT

    put_models(isolated)
    with _client(cfgdir, stt_factory=lambda: FakeSTT()) as c:
        s = c.get("/api/voice/status", headers=H).json()
    assert s["english_stt"]["ready"] and s["marathi_stt"]["ready"] and s["offline_marathi_voice"]["ready"]
    assert s["wake_word"]["model_present"] is True and s["setup_needed"] is False

    fake_packages["onnx-asr"] = False  # onnx-asr uninstalled: Marathi speech says how to get it back
    with _client(cfgdir, stt_factory=lambda: FakeSTT()) as c:
        s = c.get("/api/voice/status", headers=H).json()
    assert s["marathi_stt"]["ready"] is False and s["marathi_stt"]["package_installed"] is False
    assert "pip install onnx-asr" in s["marathi_stt"]["detail"] and s["setup_needed"] is True


def test_api_status_follows_voice_yaml(isolated, cfgdir, fake_packages):
    from jarvis.voice.stt import FakeSTT

    (cfgdir / "voice.yaml").write_text(
        "stt:\n  language: mr\n  marathi_engine: none\n"
        "tts:\n  marathi:\n    offline_engine: none\n    cloud_enabled: true\n"
        "wake_word:\n  enabled: true\n", encoding="utf-8")
    with _client(cfgdir, stt_factory=lambda: FakeSTT()) as c:
        s = c.get("/api/voice/status", headers=H).json()
    assert s["stt_language"] == "mr" and "with Whisper" in s["stt_language_detail"]
    assert s["marathi_stt"]["enabled"] is False and s["offline_marathi_voice"]["enabled"] is False
    assert s["cloud_marathi_voice"]["enabled"] is True and s["cloud_marathi_voice"]["max_privacy"] == "P1"
    assert s["wake_word"]["enabled"] is True and s["wake_word"]["ready"] is False
    assert "jarvis voice setup --model hey_jarvis" in s["wake_word"]["detail"]


def test_api_status_needs_the_token(isolated, cfgdir, fake_packages):
    with _client(cfgdir) as c:
        assert c.get("/api/voice/status").status_code in (401, 403)
