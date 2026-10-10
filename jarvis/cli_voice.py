"""Voice commands: jarvis voice [run|setup|devices] | jarvis say <text>.

Wired into jarvis/cli.py with `register(sub)` and `HANDLERS`. Also runs on its own:
`python -m jarvis.cli_voice say "Good evening, sir."`
"""

from __future__ import annotations

import argparse
import sys
from typing import Any, TextIO

from jarvis.control.audit import AuditLog
from jarvis.control.stop import StopSwitch
from jarvis.paths import default_paths
from jarvis.voice.base import VoiceUnavailable
from jarvis.voice.config import load_voice_config
from jarvis.voice.models import VOICE_MODELS
from jarvis.voice.stt import WHISPER_MODELS, language_hint, make_stt
from jarvis.voice.tts import make_local_tts, make_speech


def register(sub: Any) -> None:
    v = sub.add_parser("voice", help="talk to Jarvis (push-to-talk), set up speech models, list audio devices")
    v.add_argument("action", nargs="?", default="run", choices=["run", "setup", "devices"])
    v.add_argument("--provider", default=None, help="reasoning provider override (e.g. fake)")
    v.add_argument("--model", default=None,
                   help=f"setup: download one model only: a Whisper size ({', '.join(WHISPER_MODELS)}) "
                        f"or a voice model ({', '.join(VOICE_MODELS)}); default: everything voice.yaml uses")
    v.add_argument("--yes", action="store_true", help="setup: do not ask before downloading")

    s = sub.add_parser("say", help="speak a sentence with Jarvis's voice")
    s.add_argument("text", nargs="+")
    s.add_argument("--lang", choices=["en", "mr"], default=None, help="default: detected from the script")
    s.add_argument("--cloud", action="store_true",
                   help="allow the cloud Marathi voice for this sentence (privacy rules still apply)")
    s.add_argument("--private", action="store_true", help="mark the text sensitive (P2): never a cloud voice")


def cmd_say(args: argparse.Namespace, out: TextIO, speech: Any = None) -> int:
    paths = default_paths()
    if StopSwitch(paths.data).engaged():
        print("Emergency stop is ON (jarvis resume to release).", file=out)
        return 1
    cfg = load_voice_config()
    text = " ".join(args.text)
    speech = speech or make_speech(cfg, paths.home, AuditLog(paths.audit_log),
                                   force_cloud=True if args.cloud else None)
    try:
        res = speech.speak(text, language=args.lang, sensitivity="P2" if args.private else "P1")
    except VoiceUnavailable as e:
        print(f"Cannot speak: {e}", file=out)
        return 1
    if res.note:
        print(f"({res.note})", file=out)
    print(f"Speaking with {res.engine}{' (cloud)' if res.cloud else ''}.", file=out)
    try:
        res.playback.wait()
    except KeyboardInterrupt:
        res.playback.stop()
    return 0


def cmd_devices(out: TextIO, sd: Any = None, cfg: dict[str, Any] | None = None, home: Any = None,
                tts: Any = None, packages: Any = None) -> int:
    """Audio devices, then the state of every voice part (no model is loaded, nothing downloaded)."""
    from jarvis.voice.recorder import list_devices
    from jarvis.voice.status import status_lines, voice_status

    cfg = cfg if cfg is not None else load_voice_config()
    home = home if home is not None else default_paths().home
    try:
        devices = list_devices(sd)
        print("Microphones:", file=out)
        for d in devices:
            if d["inputs"]:
                print(f"  [{d['index']}] {d['name']}", file=out)
        print("Speakers:", file=out)
        for d in devices:
            if d["outputs"]:
                print(f"  [{d['index']}] {d['name']}", file=out)
    except VoiceUnavailable as e:
        print(f"Audio devices: {e}", file=out)
    for line in status_lines(voice_status(cfg, home, packages)):
        print(line, file=out)
    tts = tts if tts is not None else make_local_tts(cfg)
    if tts is not None and hasattr(tts, "voices"):
        print("System voices (tts.voice in config/voice.yaml):", file=out)
        try:
            for name in tts.voices():
                print(f"  {name}", file=out)
        except Exception as e:  # noqa: BLE001 (listing is informational)
            print(f"  could not list voices: {e}", file=out)
    return 0


def cmd_voice(args: argparse.Namespace, out: TextIO, inp: TextIO, stt: Any = None, speech: Any = None,
              recorder: Any = None, wakeword: Any = None) -> int:
    from jarvis.core.runtime import make_chat, open_runtime
    from jarvis.routing.policy import RoutingError
    from jarvis.voice.approval import voice_approver
    from jarvis.voice.loop import VoiceLoop, VoiceStyleContext, voice_style
    from jarvis.voice.recorder import SoundDeviceRecorder
    from jarvis.voice.setup import run_setup
    from jarvis.voice.vad import EnergyVAD
    from jarvis.voice.wakeword import make_wakeword

    cfg = load_voice_config()
    if args.action == "devices":
        return cmd_devices(out)
    rt = open_runtime()
    try:
        home = rt.paths.home
        if args.action == "setup":
            return run_setup(cfg, home, out, inp, args.model, args.yes, rt.audit)
        stt = stt or make_stt(cfg, home)
        if hasattr(stt, "check"):
            try:
                stt.check()
            except VoiceUnavailable as e:
                print(f"Speech-to-text not ready: {e}. You can still type.", file=out)
        speech = speech or make_speech(cfg, home, rt.audit)
        rec_cfg = cfg["recorder"]
        recorder = recorder or SoundDeviceRecorder(lambda: inp.readline(), int(rec_cfg["sample_rate"]),
                                                   rec_cfg.get("device"), float(rec_cfg["max_seconds"]))
        hint = language_hint(cfg)
        min_conf = float(cfg["stt"]["min_confidence"])
        approver = voice_approver(speech, stt, recorder, out, inp, rt.audit, min_conf, hint)
        try:
            session = make_chat(rt, args.provider, approver)
        except RoutingError as e:
            print(f"Routing error: {e}", file=out)
            return 2
        session.context = VoiceStyleContext(session.context, voice_style())
        vad_cfg = cfg["vad"]
        vad = EnergyVAD(float(vad_cfg["threshold_rms"]), int(vad_cfg["min_speech_ms"]))
        loop = VoiceLoop(session, stt, speech, recorder, rt.audit, session.stop, cfg, out, inp, home,
                         wakeword=wakeword if wakeword is not None else make_wakeword(cfg), mic_vad=vad,
                         language_hint=hint)
        rt.audit.write("voice_session", session_id=session.session_id, stt=getattr(stt, "name", None),
                       barge_in=cfg.get("barge_in"), wake_word=loop.wakeword is not None)
        code = loop.run()
        try:
            saved = [r for r in session.end() if r[0] in ("ADD", "UPDATE", "SUPERSEDE")]
            if saved:
                print("Learned: " + ", ".join(f"{a.lower()} {mid}" for a, mid in saved), file=out)
        except Exception as e:  # noqa: BLE001 (memory saving must not crash the exit)
            print(f"Could not save memories: {e}", file=out)
        return code
    finally:
        rt.close()


HANDLERS = {
    "voice": lambda args, out, inp: cmd_voice(args, out, inp),
    "say": lambda args, out, inp: cmd_say(args, out),
}


def main(argv: list[str] | None = None, out: TextIO | None = None, inp: TextIO | None = None) -> int:
    if out is None:
        for stream in (sys.stdout, sys.stdin):
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8")
    out = out or sys.stdout
    inp = inp or sys.stdin
    p = argparse.ArgumentParser(prog="jarvis")
    sub = p.add_subparsers(dest="command", required=True)
    register(sub)
    args = p.parse_args(argv)
    return HANDLERS[args.command](args, out, inp)


if __name__ == "__main__":
    sys.exit(main())
