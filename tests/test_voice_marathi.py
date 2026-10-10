"""Marathi voice: IndicConformer speech-to-text, language routing, the offline MMS voice, model
downloads and the wake-word model folder. Offline: fakes only, nothing is downloaded.

Real models (opt-in): JARVIS_VOICE_MODELS=<a JARVIS_HOME that has data/models/...> runs the last
tests against the downloaded files; without it they skip.
"""

import io
import json
import math
import os
import shutil
import subprocess
import sys
from array import array
from pathlib import Path
from types import SimpleNamespace

import pytest

from jarvis.control.audit import AuditLog
from jarvis.voice import models as models_mod
from jarvis.voice import stt as stt_mod
from jarvis.voice.base import Audio, Transcript, VoiceUnavailable
from jarvis.voice.config import load_voice_config
from jarvis.voice.mms_tts import MmsTTS, VitsTokenizer, marathi_number, prepare_text
from jarvis.voice.models import HEY_JARVIS, INDICCONFORMER_MR, MMS_TTS_MAR, ChecksumError, ModelFile, VoiceModel
from jarvis.voice.setup import plan, run_setup
from jarvis.voice.stt import (
    FakeSTT,
    FasterWhisperSTT,
    IndicConformerSTT,
    LanguageRouter,
    make_stt,
    transcript_from_ctc,
)
from jarvis.voice.tts import FakeTTS, SpeechOutput, make_speech
from jarvis.voice.wakeword import OpenWakeWordDetector, find_model, make_wakeword

SR = 16000
MARATHI = "उद्या सकाळी दहा वाजता बैठक आहे."


def tone(ms: int = 300, freq: float = 300.0) -> Audio:
    n = SR * ms // 1000
    return Audio(array("h", (int(6000 * math.sin(2 * math.pi * freq * i / SR)) for i in range(n))).tobytes())


# ---- IndicConformer (Marathi speech-to-text) ----

def test_ctc_scores_map_to_confidence():
    sure = transcript_from_ctc(" उद्या  सकाळी ", [-0.01, -0.05, -0.02])
    assert sure.text == "उद्या सकाळी" and sure.language == "mr" and sure.confidence > 0.95
    unsure = transcript_from_ctc("काहीतरी", [-1.5, -2.0])
    assert unsure.confidence < 0.3
    assert transcript_from_ctc("", [-0.1]) == Transcript("", "mr", 0.0)
    assert transcript_from_ctc("हो", None).confidence == 0.5


def test_indicconformer_says_how_to_set_up(tmp_path):
    missing_pkg = IndicConformerSTT(tmp_path, installed=lambda: False)
    with pytest.raises(VoiceUnavailable, match="pip install onnx-asr"):
        missing_pkg.check()
    no_model = IndicConformerSTT(tmp_path, installed=lambda: True)
    with pytest.raises(VoiceUnavailable, match=r"jarvis voice setup.*indicconformer-mr, 138 MB"):
        no_model.transcribe(tone())


def _fake_model_files(home: Path, model: VoiceModel) -> Path:
    folder = model.path(home)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / model.ready_file).write_bytes(b"fake")
    return folder


def test_indicconformer_transcribes_with_a_fake_model(tmp_path):
    np = pytest.importorskip("numpy")
    folder = _fake_model_files(tmp_path, INDICCONFORMER_MR)
    seen = {}

    class FakeAsr:
        def recognize(self, samples, sample_rate):
            seen.update(dtype=samples.dtype, n=len(samples), rate=sample_rate, peak=float(np.abs(samples).max()))
            return SimpleNamespace(text="उद्या सकाळी बैठक", logprobs=[-0.05, -0.1, -0.02])

    loads = []
    engine = IndicConformerSTT(tmp_path, loader=lambda p: loads.append(p) or FakeAsr(), installed=lambda: True)
    audio = tone(500)
    t1, t2 = engine.transcribe(audio), engine.transcribe(audio)
    assert t1 == t2 and t1.text == "उद्या सकाळी बैठक" and t1.language == "mr" and t1.confidence > 0.9
    assert loads == [folder]  # loaded once, from the local folder
    assert seen["dtype"] == np.float32 and seen["n"] == SR // 2 and seen["rate"] == SR and seen["peak"] <= 1.0


# ---- language routing ----

class FakeWhisper:
    name = "faster_whisper"

    def __init__(self, detected="en"):
        self.detected = detected
        self.calls = []
        self.checked = 0

    def check(self):
        self.checked += 1

    def transcribe(self, audio, language_hint=None):
        self.calls.append(("transcribe", language_hint))
        return Transcript("hello", "en", 0.9)

    def transcribe_if_english(self, audio):
        self.calls.append(("detect", None))
        if self.detected != "en":
            return None, self.detected, 0.7
        return Transcript("good evening", "en", 0.88), "en", 0.99


class FakeMarathi(FakeSTT):
    name = "indicconformer"

    def __init__(self, ready=True):
        super().__init__([Transcript("नमस्कार", "mr", 0.93)] * 5)
        self.ready = ready

    def check(self):
        if not self.ready:
            raise VoiceUnavailable("the Marathi speech model is not downloaded: run `jarvis voice setup`")


def test_router_modes_and_hints():
    en, mr = FakeWhisper(), FakeMarathi()
    assert LanguageRouter(en, mr, "en").transcribe(tone()) == Transcript("hello", "en", 0.9, "faster_whisper")
    assert LanguageRouter(en, mr, "mr").transcribe(tone()) == Transcript("नमस्कार", "mr", 0.93, "indicconformer")
    auto = LanguageRouter(en, mr, "auto")
    assert auto.transcribe(tone()).engine == "faster_whisper" and en.calls[-1] == ("detect", None)
    assert auto.transcribe(tone(), "mr").engine == "indicconformer"  # a hint overrides the mode
    assert auto.name == "faster_whisper+indicconformer"
    with pytest.raises(ValueError):
        LanguageRouter(en, mr, "hi")


@pytest.mark.parametrize("detected", ["mr", "hi", "si", "bn"])
def test_auto_sends_every_non_english_language_to_marathi(detected):
    # Whisper labels Marathi speech as mr, hi, si or bn (measured on FLEURS Marathi, 2026-10-10).
    en, mr = FakeWhisper(detected), FakeMarathi()
    t = LanguageRouter(en, mr, "auto").transcribe(tone())
    assert t.text == "नमस्कार" and t.language == "mr" and t.engine == "indicconformer"
    assert ("transcribe", None) not in en.calls  # Whisper never decoded the Marathi audio


def test_router_check_only_needs_the_engine_of_its_mode():
    en, missing = FakeWhisper(), FakeMarathi(ready=False)
    LanguageRouter(en, missing, "auto").check()  # English keeps working without the Marathi model
    assert en.checked == 1
    assert LanguageRouter(en, missing, "auto").marathi_ready()[0] is False
    with pytest.raises(VoiceUnavailable, match="jarvis voice setup"):
        LanguageRouter(en, missing, "mr").check()


def test_whisper_skips_decoding_non_english(tmp_path):
    pytest.importorskip("numpy")

    def never():
        raise AssertionError("segments must not be decoded")
        yield  # pragma: no cover

    class Model:
        def __init__(self, language):
            self.language = language

        def transcribe(self, samples, language, beam_size, vad_filter):
            assert language is None and vad_filter
            info = SimpleNamespace(language=self.language, language_probability=0.8)
            if self.language != "en":
                return never(), info
            return iter([SimpleNamespace(text=" Hello Jarvis.", avg_logprob=-0.1, no_speech_prob=0.01)]), info

    w = FasterWhisperSTT(tmp_path)
    w._whisper = Model("mr")
    assert w.transcribe_if_english(tone()) == (None, "mr", 0.8)
    w._whisper = Model("en")
    t, lang, _ = w.transcribe_if_english(tone())
    assert t.text == "Hello Jarvis." and lang == "en"


def test_make_stt_routes_when_a_marathi_engine_is_set(tmp_path):
    cfg = load_voice_config()
    assert cfg["stt"]["marathi_engine"] == "indicconformer" and cfg["stt"]["language"] == "auto"
    stt = make_stt(cfg, tmp_path)
    assert isinstance(stt, LanguageRouter) and isinstance(stt.marathi, IndicConformerSTT) and stt.mode == "auto"
    plain = make_stt({"stt": {"engine": "faster_whisper", "marathi_engine": "none"}}, tmp_path)
    assert isinstance(plain, FasterWhisperSTT)
    with pytest.raises(ValueError):
        make_stt({"stt": {"engine": "faster_whisper", "marathi_engine": "indicwhisper"}}, tmp_path)


def test_loop_audits_the_engine_that_heard(isolated):
    from jarvis.control.stop import StopSwitch
    from jarvis.voice.loop import VoiceLoop

    audit = AuditLog(isolated / "data" / "audit.jsonl")
    router = LanguageRouter(FakeWhisper("mr"), FakeMarathi(), "auto")
    session = SimpleNamespace(session_id="s1", send=lambda text: "ठीक आहे.")
    loop = VoiceLoop(session, router, SpeechOutput(FakeTTS("local")), None, audit, StopSwitch(isolated / "data"),
                     load_voice_config(), io.StringIO(), io.StringIO(), isolated)
    assert loop.handle_audio(tone()).status == "replied"
    turn = [json.loads(l) for l in (isolated / "data" / "audit.jsonl").read_text(encoding="utf-8").splitlines()
            if json.loads(l)["event"] == "voice_turn"][0]
    assert turn["stt_engine"] == "indicconformer" and turn["language"] == "mr"
    assert "नमस्कार" not in json.dumps(turn, ensure_ascii=False)  # lengths only, never the words


# ---- offline Marathi voice (MMS-TTS) ----

@pytest.mark.parametrize("n,words", [
    (0, "शून्य"), (9, "नऊ"), (15, "पंधरा"), (19, "एकोणीस"), (45, "पंचेचाळीस"), (99, "नव्व्याण्णव"),
    (100, "शंभर"), (150, "एकशे पन्नास"), (300, "तीनशे"), (2026, "दोन हजार सव्वीस"),
    (150000, "एक लाख पन्नास हजार"), (20000000, "दोन कोटी"),
])
def test_marathi_numbers(n, words):
    assert marathi_number(n) == words


def test_text_is_prepared_for_the_model():
    chunks = prepare_text("बिल ₹1,250 आहे. उद्या 9 वाजता meeting आहे! ५० टक्के झाले?")
    assert chunks == ["बिल एक हजार दोनशे पन्नास रुपये आहे.", "उद्या नऊ वाजता मीतिन्ग आहे!", "पन्नास टक्के झाले?"]
    assert prepare_text("डॉक्टर ॲप ऑफिस") == ["डोक्टर एप ओफिस"]  # signs the model lacks map to near letters
    long = prepare_text(" ".join(["शब्द"] * 200))
    assert len(long) > 1 and all(len(c) <= 250 for c in long)
    assert prepare_text("   ") == []


def _vocab(tmp_path: Path) -> Path:
    folder = MMS_TTS_MAR.path(tmp_path)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "vocab.json").write_text(json.dumps({"ङ": 0, " ": 1, "न": 2, "म": 3, "स": 4, "्": 5, "क": 6,
                                                   "ा": 7, "र": 8}, ensure_ascii=False), encoding="utf-8")
    (folder / "tokenizer_config.json").write_text(json.dumps({"add_blank": True, "is_uroman": False,
                                                              "pad_token": "ङ"}, ensure_ascii=False),
                                                  encoding="utf-8")
    return folder


def test_vits_tokenizer_interleaves_blanks(tmp_path):
    tok = VitsTokenizer.from_dir(_vocab(tmp_path))
    assert tok.encode("नम!") == [0, 2, 0, 3, 0]  # unknown characters are dropped
    assert tok.encode("न ") == [0, 2, 0]
    (tmp_path / "u").mkdir()
    (tmp_path / "u" / "vocab.json").write_text("{}", encoding="utf-8")
    (tmp_path / "u" / "tokenizer_config.json").write_text('{"is_uroman": true}', encoding="utf-8")
    with pytest.raises(VoiceUnavailable, match="uroman"):
        VitsTokenizer.from_dir(tmp_path / "u")


class Recorded:
    def __init__(self):
        self.calls = []

    def __call__(self, argv, **kw):
        self.calls.append((argv, kw))
        return SimpleNamespace(poll=lambda: None, wait=lambda timeout=None: 0, terminate=lambda: None,
                               kill=lambda: None)


def test_mms_says_how_to_set_up(tmp_path):
    with pytest.raises(VoiceUnavailable, match=r"jarvis voice setup.*mms-tts-mar, 115 MB"):
        MmsTTS(tmp_path, tmp_path / "tmp", Recorded()).speak(MARATHI)


def test_mms_synthesizes_plays_and_cleans_up(tmp_path):
    np = pytest.importorskip("numpy")
    folder = _vocab(tmp_path)
    (folder / "model.onnx").write_bytes(b"fake")
    runs = []

    class Session:
        def run(self, names, feeds):
            runs.append(feeds["input_ids"].tolist())
            assert feeds["attention_mask"].shape == feeds["input_ids"].shape
            return [np.full((1, 1600), 0.5, dtype=np.float32), np.zeros((1, 192, 4), dtype=np.float32)]

    popen = Recorded()
    tts = MmsTTS(tmp_path, tmp_path / "tmp", popen, platform="darwin", session_factory=lambda p: Session(),
                 installed=lambda: True)
    audio = tts.synthesize("नमस्कार. नमस्कार")
    assert len(runs) == 2 and audio.sample_rate == SR
    assert audio.seconds == pytest.approx(0.1 + 0.25 + 0.1)  # two sentences and one pause
    pb = tts.speak("नमस्कार")
    argv, kw = popen.calls[0]
    wav = Path(argv[1])
    assert argv[0] == "afplay" and wav.suffix == ".wav" and wav.exists() and kw["shell"] is False
    assert Audio.from_wav(wav.read_bytes()).sample_rate == SR
    pb.wait()
    assert not wav.exists()  # the temporary audio is deleted after playing
    assert tts.speak("!!!").wait() is True and len(popen.calls) == 1  # nothing to say: nothing played


def test_marathi_prefers_the_offline_voice_even_when_cloud_is_on():
    system, cloud, offline = FakeTTS("mac_say"), FakeTTS("edge_tts", cloud=True), FakeTTS("mms_tts")
    speech = SpeechOutput(system, cloud, "P1", local_marathi=offline)
    res = speech.speak(MARATHI)
    assert res.engine == "mms_tts" and not res.cloud and offline.spoken == [(MARATHI, "mr")]
    assert speech.speak("Good evening, sir.").engine == "mac_say"  # English never uses the Marathi voice
    assert cloud.spoken == []


def test_offline_voice_missing_falls_back_safely(tmp_path):
    def unavailable(text, language="mr"):
        raise VoiceUnavailable("not downloaded: run `jarvis voice setup`")

    offline, system, cloud = FakeTTS("mms_tts"), FakeTTS("mac_say"), FakeTTS("edge_tts", cloud=True)
    offline.speak = unavailable
    res = SpeechOutput(system, None, local_marathi=offline).speak(MARATHI)
    assert res.engine == "mac_say" and "offline Marathi voice unavailable" in res.note
    with_cloud = SpeechOutput(system, cloud, "P1", local_marathi=offline)
    assert with_cloud.speak(MARATHI).engine == "edge_tts"  # P1 may use the enabled cloud voice
    assert not with_cloud.speak("माझा पासवर्ड आहे hunter22 लक्षात ठेवा", language="mr").cloud  # P3: never
    assert not with_cloud.speak(MARATHI, sensitivity="P2").cloud
    assert all("hunter22" not in t for t, _ in cloud.spoken)


def test_offline_voice_error_is_audited_and_does_not_silence(tmp_path):
    audit = AuditLog(tmp_path / "audit.jsonl")
    offline, system = FakeTTS("mms_tts"), FakeTTS("mac_say")
    offline.speak = lambda text, language="mr": 1 / 0
    res = SpeechOutput(system, None, audit=audit, local_marathi=offline).speak(MARATHI)
    assert res.engine == "mac_say" and "ZeroDivisionError" in res.note
    assert "voice_tts_error" in (tmp_path / "audit.jsonl").read_text(encoding="utf-8")


def test_default_speech_has_the_offline_voice_but_works_without_it(tmp_path):
    speech = make_speech(load_voice_config(), tmp_path, platform="win32", popen=Recorded())
    assert isinstance(speech.local_marathi, MmsTTS) and speech.cloud_marathi is None
    res = speech.speak(MARATHI)  # model not downloaded in this test home
    assert res.engine == "windows_sapi" and "jarvis voice setup" in res.note
    off = load_voice_config()
    off["tts"]["marathi"]["offline_engine"] = "none"
    assert make_speech(off, tmp_path, platform="win32", popen=Recorded()).local_marathi is None
    off["tts"]["marathi"]["offline_engine"] = "piper"
    with pytest.raises(ValueError):
        make_speech(off, tmp_path, platform="win32", popen=Recorded())


# ---- model downloads (pinned, hash-checked) ----

def _fetcher(content: dict[str, bytes], calls: list):
    def fetch(repo, filename, revision, dest):
        calls.append((repo, filename, revision))
        (dest / filename).write_bytes(content.get(filename, b"{}"))
        return dest / filename
    return fetch


def test_download_pins_revisions_and_checks_hashes(tmp_path):
    import hashlib

    good = b"weights"
    m = VoiceModel("demo", "Demo", "demo", "org/demo", "abc123",
                   (ModelFile("config.json"), ModelFile("model.onnx", hashlib.sha256(good).hexdigest(),
                                                        repo="other/demo", revision="def456")),
                   1, "MIT", "model.onnx")
    calls = []
    models_mod.download(m, tmp_path, _fetcher({"model.onnx": good}, calls))
    assert calls == [("org/demo", "config.json", "abc123"), ("other/demo", "model.onnx", "def456")]
    assert m.present(tmp_path)
    models_mod.download(m, tmp_path, _fetcher({}, calls))
    assert len(calls) == 2  # files already there and matching: nothing fetched again
    (m.path(tmp_path) / "model.onnx").unlink()
    with pytest.raises(ChecksumError):
        models_mod.download(m, tmp_path, _fetcher({"model.onnx": b"tampered"}, calls))
    assert not (m.path(tmp_path) / "model.onnx").exists()  # a bad file is deleted, never used


def test_model_registry_is_pinned_and_local():
    for m in (INDICCONFORMER_MR, MMS_TTS_MAR):
        assert len(m.revision) == 40 and any(f.sha256 for f in m.files)
        assert m.ready_file in {f.name for f in m.files}
    assert "CC-BY-NC" in MMS_TTS_MAR.license and "MIT" in INDICCONFORMER_MR.license
    assert "NC" in HEY_JARVIS.license
    assert INDICCONFORMER_MR.path(Path("/h")) == Path("/h/data/models/indicconformer/mr")


# ---- setup ----

def test_setup_plan_follows_the_config(tmp_path):
    cfg = load_voice_config()
    assert [i.key for i in plan(cfg, tmp_path)] == ["whisper-small", "indicconformer-mr", "mms-tts-mar"]
    cfg["wake_word"]["enabled"] = True
    cfg["stt"]["marathi_engine"] = "none"
    assert [i.key for i in plan(cfg, tmp_path)] == ["whisper-small", "mms-tts-mar", "hey_jarvis"]
    assert [i.key for i in plan(cfg, tmp_path, "hey_jarvis")] == ["hey_jarvis"]
    assert plan(cfg, tmp_path, "giant") is None


def test_setup_asks_once_with_the_total(tmp_path):
    out, calls = io.StringIO(), []
    code = run_setup(load_voice_config(), tmp_path, out, io.StringIO("n\n"), downloader=lambda m, d: calls.append(m),
                     installed=lambda: True, fetch=_fetcher({}, calls))
    text = out.getvalue()
    assert code == 1 and calls == [] and text.count("[y/N]") == 1
    assert f"Download {486 + 138 + 115} MB now?" in text and "CC-BY-NC" in text and "Not downloaded." in text


def test_setup_downloads_one_component_and_audits(tmp_path):
    out = io.StringIO()
    audit = AuditLog(tmp_path / "audit.jsonl")
    made = []

    def wake(home):
        folder = HEY_JARVIS.path(home)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "hey_jarvis_v0.1.onnx").write_bytes(b"x")
        made.append(home)

    assert run_setup(load_voice_config(), tmp_path, out, io.StringIO("ho\n"), "hey_jarvis", audit=audit,
                     wake_downloader=wake) == 0
    assert made == [tmp_path] and "done" in out.getvalue()
    assert '"voice_setup"' in (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    assert run_setup(load_voice_config(), tmp_path, out, io.StringIO(""), "hey_jarvis") == 0
    assert "already downloaded" in out.getvalue()


def test_setup_reports_a_failed_download(tmp_path):
    def broken(repo, filename, revision, dest):
        raise ConnectionError("offline")

    out = io.StringIO()
    assert run_setup(load_voice_config(), tmp_path, out, io.StringIO(), "indicconformer-mr", assume_yes=True,
                     fetch=broken) == 1
    assert "download failed (ConnectionError: offline)" in out.getvalue()


def test_setup_lists_every_choice_for_an_unknown_name(tmp_path):
    out = io.StringIO()
    assert run_setup(load_voice_config(), tmp_path, out, io.StringIO(), "giant") == 2
    for name in ("small", "indicconformer-mr", "mms-tts-mar", "hey_jarvis"):
        assert name in out.getvalue()


# ---- wake word model folder ----

def test_wake_word_uses_jarvis_model_folder(tmp_path):
    folder = HEY_JARVIS.path(tmp_path)
    folder.mkdir(parents=True)
    for name in ("hey_jarvis_v0.1.onnx", "melspectrogram.onnx", "embedding_model.onnx"):
        (folder / name).write_bytes(b"x")
    assert find_model(folder, "hey_jarvis") == folder / "hey_jarvis_v0.1.onnx"
    assert find_model(folder, "alexa") is None and find_model(None, "hey_jarvis") is None
    calls = []

    def factory(**kw):
        calls.append(kw)
        return SimpleNamespace(predict=lambda x: {"hey_jarvis_v0.1": 0.0})

    det = make_wakeword({"wake_word": {"enabled": True, "model": "hey_jarvis"}}, tmp_path)
    det._factory = factory
    det._load()
    assert calls == [{"wakeword_models": [str(folder / "hey_jarvis_v0.1.onnx")], "inference_framework": "onnx",
                      "melspec_model_path": str(folder / "melspectrogram.onnx"),
                      "embedding_model_path": str(folder / "embedding_model.onnx")}]


# ---- real models (opt-in, offline: the files must already be downloaded) ----

REAL_HOME = os.environ.get("JARVIS_VOICE_MODELS")


def _real_home(*needed: VoiceModel) -> Path:
    if not REAL_HOME:
        pytest.skip("set JARVIS_VOICE_MODELS=<JARVIS_HOME with downloaded voice models>")
    home = Path(REAL_HOME)
    missing = [m.key for m in needed if not m.present(home)]
    if missing:
        pytest.skip(f"models not downloaded: {', '.join(missing)} (jarvis voice setup)")
    pytest.importorskip("onnxruntime")
    return home


def test_real_marathi_voice_is_understood_by_the_marathi_model(tmp_path):
    home = _real_home(INDICCONFORMER_MR, MMS_TTS_MAR)
    pytest.importorskip("onnx_asr")
    audio = MmsTTS(home, tmp_path).synthesize("तुमच्या खात्यात तीन नवीन संदेश आले आहेत.")
    assert 1.0 < audio.seconds < 8.0
    heard = IndicConformerSTT(home).transcribe(audio)
    assert heard.language == "mr" and "संदेश" in heard.text and heard.confidence > 0.6


@pytest.mark.skipif(sys.platform != "darwin" or not shutil.which("say"), reason="needs macOS `say`")
def test_real_english_goes_to_whisper(tmp_path):
    home = _real_home(INDICCONFORMER_MR)
    if not stt_mod.model_present(home, "small"):
        pytest.skip("Whisper small not downloaded")
    wav = tmp_path / "en.wav"
    subprocess.run(["say", "-o", str(wav), "--data-format=LEI16@16000", "Remind me to buy milk tomorrow."],
                   check=True, shell=False, timeout=60)
    t = LanguageRouter(FasterWhisperSTT(home), IndicConformerSTT(home), "auto").transcribe(Audio.from_wav(wav.read_bytes()))
    assert t.engine == "faster_whisper" and t.language == "en" and "milk" in t.text.lower()
