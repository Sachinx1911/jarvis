"""What the voice setup looks like on this machine, for `jarvis voice devices` and the dashboard.

Only cheap checks: is a package installed, is a model file on disk. No model is loaded and nothing
is downloaded here. Each part says what to run when something is missing.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any, Callable, Mapping

from jarvis.voice.base import VoiceUnavailable
from jarvis.voice.mms_tts import MmsTTS, onnxruntime_installed
from jarvis.voice.models import HEY_JARVIS, INDICCONFORMER_MR, MMS_TTS_MAR
from jarvis.voice.stt import (
    ONNX_ASR_HINT,
    PACKAGE_HINT,
    WHISPER_MODELS,
    IndicConformerSTT,
    faster_whisper_installed,
    model_present,
    onnx_asr_installed,
    setup_hint,
)
from jarvis.voice.tts import SpeechOutput, local_engine_name
from jarvis.voice.wakeword import PACKAGE_HINT as WAKEWORD_HINT
from jarvis.voice.wakeword import find_model

VOICE_EXTRA = 'pip install -e ".[voice]"'
SETUP_ALL = "jarvis voice setup"


def openwakeword_present() -> bool:
    # find_spec instead of importing: the package pulls in scipy and scikit-learn, which a
    # status screen should not load into the dashboard process.
    return importlib.util.find_spec("openwakeword") is not None


def package_checks() -> dict[str, Callable[[], bool]]:
    """Package name -> "is it installed?". Tests replace this with fakes."""
    return {"faster-whisper": faster_whisper_installed, "onnx-asr": onnx_asr_installed,
            "onnxruntime": onnxruntime_installed, "openwakeword": openwakeword_present}


def _setup(key: str) -> str:
    return f"{SETUP_ALL} --model {key}"


def _engine_check(engine: Any) -> tuple[bool, str]:
    """Run an engine's own check() (cheap: package import and file presence, no model load)."""
    try:
        engine.check()
    except VoiceUnavailable as e:
        return False, str(e)
    return True, "ready"


def _language(stt: dict[str, Any]) -> tuple[str, str]:
    mode = str(stt.get("language") or "auto").lower()
    marathi = str(stt.get("marathi_engine") or "none").lower()
    if mode == "en":
        return mode, "English only (Whisper)"
    if mode == "mr":
        if marathi == "none":
            return mode, "Marathi only, with Whisper (no Marathi engine set)"
        return mode, f"Marathi only ({marathi})"
    if mode == "auto":
        if marathi == "none":
            return mode, "Whisper handles every language (no Marathi engine set)"
        return mode, "English goes to Whisper, other speech to the Marathi engine"
    return mode, f"unknown mode {mode!r} (choose auto, en or mr in config/voice.yaml stt.language)"


def _english(stt: dict[str, Any], home: Path, pk: Callable[[str], bool]) -> dict[str, Any]:
    engine = str(stt.get("engine", "faster_whisper"))
    model = str(stt.get("model", "small"))
    out: dict[str, Any] = {"engine": engine, "model": model, "model_mb": WHISPER_MODELS.get(model, ("", 0))[1],
                           "title": f"Whisper {model!r}", "package": "faster-whisper",
                           "package_installed": False, "model_present": False, "ready": False, "detail": "",
                           "install_hint": VOICE_EXTRA, "package_hint": PACKAGE_HINT, "setup": _setup(model)}
    if engine == "fake":
        out.update(title="fake engine (tests only)", package="", package_installed=True, model_present=True,
                   ready=True, detail="ready", install_hint="", package_hint="", setup="")
        return out
    if engine != "faster_whisper":
        out["detail"] = f"unknown speech-to-text engine {engine!r} (config/voice.yaml stt.engine)"
        return out
    out["package_installed"] = pk("faster-whisper")
    out["model_present"] = model_present(home, model)
    # Same wording as FasterWhisperSTT.check().
    if not out["package_installed"]:
        out["detail"] = f"faster-whisper is not installed: {PACKAGE_HINT}; then {setup_hint(model)}"
    elif not out["model_present"]:
        out["detail"] = f"Whisper model {model!r} is not downloaded: {setup_hint(model)}"
    else:
        out["ready"], out["detail"] = True, "ready"
    return out


def _marathi_stt(stt: dict[str, Any], home: Path, pk: Callable[[str], bool]) -> dict[str, Any]:
    engine = str(stt.get("marathi_engine") or "none").lower()
    m = INDICCONFORMER_MR
    out: dict[str, Any] = {"engine": engine, "enabled": engine != "none", "model": m.key, "model_mb": m.mb,
                           "title": m.title, "package": "onnx-asr", "package_installed": pk("onnx-asr"),
                           "model_present": m.present(home), "ready": False, "detail": "",
                           "install_hint": VOICE_EXTRA, "package_hint": ONNX_ASR_HINT, "setup": _setup(m.key)}
    if engine == "none":
        out["detail"] = "off (config/voice.yaml stt.marathi_engine: none): Whisper hears Marathi too, poorly"
    elif engine != "indicconformer":
        out["detail"] = f"unknown Marathi speech-to-text engine {engine!r} (choose indicconformer or none)"
    else:
        out["ready"], out["detail"] = _engine_check(
            IndicConformerSTT(home, m, installed=lambda: out["package_installed"]))
    return out


def _local_voice(cfg: dict[str, Any], platform: str) -> dict[str, Any]:
    engine = local_engine_name(cfg, platform)
    if engine is None:
        return {"engine": None, "ready": False, "detail": "none on this platform (Windows and macOS only)"}
    return {"engine": engine, "ready": True, "detail": "ready"}


def _offline_marathi_voice(marathi: dict[str, Any], home: Path, pk: Callable[[str], bool]) -> dict[str, Any]:
    engine = str(marathi.get("offline_engine") or "none").lower()
    m = MMS_TTS_MAR
    out: dict[str, Any] = {"engine": engine, "enabled": engine != "none", "model": m.key, "model_mb": m.mb,
                           "title": m.title, "package": "onnxruntime", "package_installed": pk("onnxruntime"),
                           "model_present": m.present(home), "ready": False, "detail": "",
                           "install_hint": VOICE_EXTRA, "package_hint": VOICE_EXTRA, "setup": _setup(m.key)}
    if engine == "none":
        out["detail"] = "off (config/voice.yaml tts.marathi.offline_engine: none)"
    elif engine != "mms_tts":
        out["detail"] = f"unknown offline Marathi voice {engine!r} (choose mms_tts or none)"
    else:
        tmp = home / "data" / "voice" / "tmp"
        out["ready"], out["detail"] = _engine_check(MmsTTS(home, tmp, installed=lambda: out["package_installed"]))
    return out


def _cloud_marathi_voice(marathi: dict[str, Any]) -> dict[str, Any]:
    on = bool(marathi.get("cloud_enabled", False))
    engine = str(marathi.get("engine", "edge_tts"))
    voice = str(marathi.get("voice", "mr-IN-ManoharNeural"))
    cap = SpeechOutput(None, None, str(marathi.get("max_privacy", "P1"))).cloud_max_privacy  # capped at P1
    detail = (f"on: Marathi text up to {cap} may go to {engine} (cloud) when the offline voice is not available; "
              "P3 never" if on else "off (Marathi text is never sent to a cloud voice)")
    return {"enabled": on, "engine": engine, "voice": voice, "max_privacy": cap, "detail": detail}


def _wake_word(ww: dict[str, Any], home: Path, pk: Callable[[str], bool]) -> dict[str, Any]:
    enabled = bool(ww.get("enabled", False))
    engine = str(ww.get("engine", "openwakeword"))
    model = str(ww.get("model", "hey_jarvis"))
    present = find_model(HEY_JARVIS.path(home), model) is not None
    installed = pk("openwakeword")
    out: dict[str, Any] = {"enabled": enabled, "engine": engine, "model": model, "model_present": present,
                           "package": "openwakeword", "package_installed": installed, "ready": False,
                           "detail": "", "install_hint": 'pip install -e ".[wakeword]"',
                           "package_hint": WAKEWORD_HINT, "setup": _setup(model) if model == HEY_JARVIS.key else ""}
    if engine != "openwakeword":
        out["detail"] = f"unknown wake-word engine {engine!r} (config/voice.yaml wake_word.engine)"
    elif not installed:
        out["detail"] = f"openWakeWord is not installed: {WAKEWORD_HINT}"
    elif not present:
        out["detail"] = (f"wake-word model {model!r} is not downloaded: run `{out['setup']}`" if out["setup"]
                         else f"wake-word model {model!r} not found")
    else:
        out["ready"], out["detail"] = True, "ready"
    if not enabled:
        out["detail"] = f"off (config/voice.yaml wake_word.enabled); {out['detail']}"
    return out


def voice_status(cfg: dict[str, Any], home: Path,
                 packages: Mapping[str, Callable[[], bool] | bool] | None = None,
                 platform: str = sys.platform) -> dict[str, Any]:
    """Every voice part: engine, whether it is ready, why not, and the command that fixes it."""
    checks = dict(package_checks()) if packages is None else dict(packages)
    seen: dict[str, bool] = {}

    def pk(name: str) -> bool:  # each package is checked at most once, and only when asked
        if name not in seen:
            check = checks.get(name, False)
            seen[name] = bool(check() if callable(check) else check)
        return seen[name]

    stt = cfg.get("stt", {})
    marathi_tts = cfg.get("tts", {}).get("marathi", {})
    mode, mode_detail = _language(stt)
    status = {
        "stt_language": mode,
        "stt_language_detail": mode_detail,
        "english_stt": _english(stt, home, pk),
        "marathi_stt": _marathi_stt(stt, home, pk),
        "local_voice": _local_voice(cfg, platform),
        "offline_marathi_voice": _offline_marathi_voice(marathi_tts, home, pk),
        "cloud_marathi_voice": _cloud_marathi_voice(marathi_tts),
        "wake_word": _wake_word(cfg.get("wake_word", {}), home, pk),
    }
    status["setup_needed"] = setup_needed(status)
    status["setup_command"] = SETUP_ALL
    return status


def setup_needed(status: dict[str, Any]) -> bool:
    """True when a part that config/voice.yaml turns on is missing a package or a model."""
    parts = [status["english_stt"]]
    parts += [status[k] for k in ("marathi_stt", "offline_marathi_voice", "wake_word") if status[k]["enabled"]]
    return any(not p["ready"] for p in parts)


def _files(part: dict[str, Any]) -> str:
    package = f"{part['package']} {'installed' if part['package_installed'] else 'NOT installed'}"
    return f"{package}, model {'downloaded' if part['model_present'] else 'NOT downloaded'}"


def _state(part: dict[str, Any]) -> str:
    """"ready", or the one thing to do next."""
    if part["ready"]:
        return "ready"
    if part.get("package") and not part["package_installed"] and part.get("package_hint"):
        return f"NOT ready: install {part['package']} first: {part['package_hint']}"
    if not part.get("model_present", True) and part.get("setup"):
        return f"NOT ready: run `{part['setup']}`"
    return f"NOT ready: {part['detail']}"


def status_lines(status: dict[str, Any]) -> list[str]:
    """The same status as plain text lines, for the terminal."""
    en, mr, local = status["english_stt"], status["marathi_stt"], status["local_voice"]
    offline, cloud, ww = status["offline_marathi_voice"], status["cloud_marathi_voice"], status["wake_word"]

    lines = [f"Speech-to-text language: {status['stt_language']} ({status['stt_language_detail']})"]
    if en["engine"] == "faster_whisper":
        lines.append(f"English speech-to-text: Whisper {en['model']!r} ({en['model_mb']} MB): "
                     f"{_files(en)}: {_state(en)}")
    else:
        lines.append(f"English speech-to-text: {en['engine']}: {_state(en)}")
    if mr["enabled"] and mr["engine"] == "indicconformer":
        lines.append(f"Marathi speech-to-text: IndicConformer ({mr['model']}, {mr['model_mb']} MB): "
                     f"{_files(mr)}: {_state(mr)}")
    else:
        lines.append(f"Marathi speech-to-text: {mr['detail']}")
    lines.append(f"Voice (text-to-speech): {local['engine'] or local['detail']}")
    if offline["enabled"] and offline["engine"] == "mms_tts":
        lines.append(f"Offline Marathi voice: MMS-TTS ({offline['model']}, {offline['model_mb']} MB): "
                     f"{_files(offline)}: {_state(offline)}")
    else:
        lines.append(f"Offline Marathi voice: {offline['detail']}")
    lines.append(f"Marathi cloud voice ({cloud['engine']}, {cloud['voice']}): "
                 f"{'ON, up to ' + cloud['max_privacy'] if cloud['enabled'] else 'off'}")
    ww_line = f"Wake word: {'ON' if ww['enabled'] else 'off'} ({ww['engine']} {ww['model']}): {_files(ww)}"
    if ww["enabled"]:
        ww_line += f": {_state(ww)}"
    elif not ww["model_present"] and ww["setup"]:
        ww_line += f" (to use it: `{ww['setup']}`)"
    lines.append(ww_line)
    if status["setup_needed"]:
        lines.append(f"Something is missing: run `{status['setup_command']}` "
                     "(it shows the sizes and asks before downloading).")
    return lines
