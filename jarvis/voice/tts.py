"""Text-to-speech engines and the privacy-aware speech output.

Local engines (no new dependency):
- Windows: System.Speech (SAPI) through PowerShell. The text goes through an environment
  variable, never into the script, so it cannot inject commands.
- macOS: `say`. The text goes through stdin (`say` reads stdin when no message is given).

Cloud engine (optional, off by default): edge-tts, Microsoft's online speech service, for the
Marathi voice (PLAN.md 5.8). P3 text is never sent, nor anything above the configured privacy
class (capped at P1).

All processes run with list arguments and shell=False.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from jarvis.control.audit import AuditLog
from jarvis.privacy import CLASSES, allowed, find_p3, redact_p3
from jarvis.voice.base import DonePlayback, Playback, TextToSpeech, VoiceUnavailable

MAX_SPOKEN_CHARS = 4000  # Windows environment variables hold up to 32767 characters
CREATE_NO_WINDOW = 0x08000000

Popen = Callable[..., Any]

WINDOWS_SPEAK = (
    "$ErrorActionPreference = 'Stop'; "
    "Add-Type -AssemblyName System.Speech; "
    "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
    "if ($env:JARVIS_TTS_VOICE) { $s.SelectVoice($env:JARVIS_TTS_VOICE) }; "
    "$s.Rate = [int]$env:JARVIS_TTS_RATE; "
    "$s.SetOutputToDefaultAudioDevice(); "
    "$s.Speak($env:JARVIS_TTS_TEXT); "
    "$s.Dispose()"
)
WINDOWS_VOICES = (
    "Add-Type -AssemblyName System.Speech; "
    "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
    "$s.GetInstalledVoices() | ForEach-Object { $_.VoiceInfo.Name + '|' + $_.VoiceInfo.Culture }; "
    "$s.Dispose()"
)
# Plays an audio file (mp3/wav) with WPF's MediaPlayer; the path comes from the environment.
WINDOWS_PLAY_FILE = (
    "$ErrorActionPreference = 'Stop'; "
    "Add-Type -AssemblyName PresentationCore; "
    "$p = New-Object System.Windows.Media.MediaPlayer; "
    "$p.Open([Uri]::new($env:JARVIS_AUDIO_FILE)); "
    "$t = (Get-Date).AddSeconds(5); "
    "while (-not $p.NaturalDuration.HasTimeSpan -and (Get-Date) -lt $t) { Start-Sleep -Milliseconds 50 }; "
    "$p.Play(); "
    "if ($p.NaturalDuration.HasTimeSpan) { Start-Sleep -Milliseconds ([int]$p.NaturalDuration.TimeSpan.TotalMilliseconds + 300) } "
    "else { Start-Sleep -Seconds 15 }; "
    "$p.Close()"
)


def powershell_argv(script: str) -> list[str]:
    return ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script]


class ProcessPlayback:
    """Speech played by a child process. stop() ends the process, which stops the audio."""

    def __init__(self, proc: Any, cleanup: Callable[[], None] | None = None):
        self.proc = proc
        self._cleanup = cleanup

    def is_playing(self) -> bool:
        return self.proc.poll() is None

    def wait(self, timeout: float | None = None) -> bool:
        try:
            self.proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            return False
        self._done()
        return True

    def stop(self) -> None:
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self._done()

    def _done(self) -> None:
        if self._cleanup:
            cleanup, self._cleanup = self._cleanup, None
            cleanup()


def _popen_kwargs() -> dict[str, Any]:
    kw: dict[str, Any] = {"shell": False, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if sys.platform == "win32":
        kw["creationflags"] = CREATE_NO_WINDOW
    return kw


class WindowsSapiTTS:
    name = "windows_sapi"
    cloud = False

    def __init__(self, voice: str = "", rate: int = 0, popen: Popen = subprocess.Popen):
        self.voice = voice
        self.rate = max(-10, min(int(rate or 0), 10))
        self.popen = popen

    def command(self, text: str) -> tuple[list[str], dict[str, str]]:
        env = dict(os.environ)
        env.update(JARVIS_TTS_TEXT=text[:MAX_SPOKEN_CHARS], JARVIS_TTS_VOICE=self.voice or "",
                   JARVIS_TTS_RATE=str(self.rate))
        return powershell_argv(WINDOWS_SPEAK), env

    def speak(self, text: str, language: str = "en") -> Playback:
        if not text.strip():
            return DonePlayback()
        argv, env = self.command(text)
        return ProcessPlayback(self.popen(argv, env=env, **_popen_kwargs()))

    def voices(self, run: Callable[..., Any] = subprocess.run) -> list[str]:
        r = run(powershell_argv(WINDOWS_VOICES), capture_output=True, text=True, timeout=20, shell=False)
        return [l.strip() for l in (r.stdout or "").splitlines() if l.strip()]


class MacSayTTS:
    name = "mac_say"
    cloud = False

    def __init__(self, voice: str = "", rate: int = 0, popen: Popen = subprocess.Popen):
        self.voice = voice
        self.rate = int(rate or 0)
        self.popen = popen

    def command(self) -> list[str]:
        argv = ["say"]
        if self.voice:
            argv += ["-v", self.voice]
        if self.rate > 0:
            argv += ["-r", str(self.rate)]
        return argv  # the text goes through stdin, so it is never parsed as an option

    def speak(self, text: str, language: str = "en") -> Playback:
        if not text.strip():
            return DonePlayback()
        kw = _popen_kwargs()
        proc = self.popen(self.command(), stdin=subprocess.PIPE, **kw)
        try:
            proc.stdin.write(text[:MAX_SPOKEN_CHARS].encode("utf-8"))
            proc.stdin.close()
        except (BrokenPipeError, OSError):
            pass
        return ProcessPlayback(proc)

    def voices(self, run: Callable[..., Any] = subprocess.run) -> list[str]:
        r = run(["say", "-v", "?"], capture_output=True, text=True, timeout=20, shell=False)
        return [l.split("#")[0].strip() for l in (r.stdout or "").splitlines() if l.strip()]


def play_file_command(path: Path, platform: str = sys.platform) -> tuple[list[str], dict[str, str] | None]:
    if platform == "darwin":
        return ["afplay", str(path)], None
    if platform == "win32":
        env = dict(os.environ)
        env["JARVIS_AUDIO_FILE"] = str(path)
        return powershell_argv(WINDOWS_PLAY_FILE), env
    raise VoiceUnavailable("audio file playback is supported on Windows and macOS only")


class EdgeTTS:
    """CLOUD: sends text to Microsoft's online speech service (https://github.com/rany2/edge-tts).

    Used only through SpeechOutput, which enforces the privacy rules.
    """

    name = "edge_tts"
    cloud = True

    def __init__(self, voice: str, tmp_dir: Path, popen: Popen = subprocess.Popen,
                 synthesize: Callable[[str, str, Path], None] | None = None, platform: str = sys.platform):
        self.voice = voice
        self.tmp_dir = tmp_dir
        self.popen = popen
        self.synthesize = synthesize or _edge_synthesize
        self.platform = platform

    def speak(self, text: str, language: str = "mr") -> Playback:
        if not text.strip():
            return DonePlayback()
        self.tmp_dir.mkdir(parents=True, exist_ok=True)
        path = self.tmp_dir / f"tts-{uuid.uuid4().hex[:10]}.mp3"
        self.synthesize(text[:MAX_SPOKEN_CHARS], self.voice, path)
        argv, env = play_file_command(path, self.platform)
        proc = self.popen(argv, env=env, **_popen_kwargs())
        return ProcessPlayback(proc, cleanup=lambda: path.unlink(missing_ok=True))


def _edge_synthesize(text: str, voice: str, path: Path) -> None:
    try:
        import edge_tts
    except ImportError as e:
        raise VoiceUnavailable("edge-tts is not installed: pip install edge-tts==7.2.8") from e
    edge_tts.Communicate(text, voice).save_sync(str(path))


class FakePlayback:
    def __init__(self, playing: bool = False):
        self.playing = playing
        self.stopped = False

    def is_playing(self) -> bool:
        return self.playing

    def wait(self, timeout: float | None = None) -> bool:
        return not self.playing

    def stop(self) -> None:
        self.playing = False
        self.stopped = True


class FakeTTS:
    def __init__(self, name: str = "fake", cloud: bool = False, keep_playing: bool = False):
        self.name = name
        self.cloud = cloud
        self.keep_playing = keep_playing
        self.spoken: list[tuple[str, str]] = []
        self.playbacks: list[FakePlayback] = []

    def speak(self, text: str, language: str = "en") -> Playback:
        self.spoken.append((text, language))
        pb = FakePlayback(self.keep_playing)
        self.playbacks.append(pb)
        return pb


# ---- what gets spoken, and by which engine ----

_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
_LETTER = re.compile(r"[^\W\d_]")
_MARKDOWN = [(re.compile(r"\[([^\]]+)\]\([^)]+\)"), r"\1"), (re.compile(r"[*_`#>|]+"), " "),
             (re.compile(r"\s+"), " ")]


def detect_language(text: str) -> str:
    """"mr" when most letters are Devanagari, else "en". (Hindi also uses Devanagari; Jarvis speaks Marathi.)"""
    letters = _LETTER.findall(text)
    devanagari = sum(1 for c in letters if _DEVANAGARI.match(c))
    return "mr" if letters and devanagari / len(letters) > 0.3 else "en"


def spoken_text(text: str) -> str:
    """Text as it should be read aloud: secrets withheld, markdown symbols removed."""
    text, _ = redact_p3(text)
    text = text.replace("[WITHHELD]", "withheld")
    for pat, repl in _MARKDOWN:
        text = pat.sub(repl, text)
    return text.strip()


@dataclass
class SpeakResult:
    playback: Playback
    engine: str
    cloud: bool
    note: str = ""


class SpeechOutput:
    """Chooses the engine for each utterance and enforces the cloud privacy rules."""

    def __init__(self, local: TextToSpeech | None, cloud_marathi: TextToSpeech | None = None,
                 cloud_max_privacy: str = "P1", audit: AuditLog | None = None):
        self.local = local
        self.cloud_marathi = cloud_marathi
        cap = cloud_max_privacy if cloud_max_privacy in CLASSES else "P0"
        self.cloud_max_privacy = cap if CLASSES.index(cap) <= CLASSES.index("P1") else "P1"
        self.audit = audit

    def cloud_allowed(self, raw_text: str, sensitivity: str) -> tuple[bool, str]:
        if self.cloud_marathi is None:
            return False, "cloud voice disabled"
        if find_p3(raw_text):
            return False, "P3 text never goes to the cloud"
        if sensitivity not in CLASSES or not allowed(sensitivity, self.cloud_max_privacy):
            return False, f"{sensitivity} text stays local"
        return True, "ok"

    def speak(self, text: str, language: str | None = None, sensitivity: str = "P1") -> SpeakResult:
        lang = language or detect_language(text)
        say = spoken_text(text)
        note = ""
        if lang == "mr":
            ok, note = self.cloud_allowed(text, sensitivity)
            if ok:
                try:
                    pb = self.cloud_marathi.speak(say, lang)  # type: ignore[union-attr]
                    self._log(self.cloud_marathi.name, True, lang, say)  # type: ignore[union-attr]
                    return SpeakResult(pb, self.cloud_marathi.name, True)  # type: ignore[union-attr]
                except Exception as e:  # network or package problems: fall back to the local voice
                    note = f"cloud voice failed ({type(e).__name__}); used the local voice"
                    if self.audit:
                        self.audit.write("voice_cloud_tts_error", engine=self.cloud_marathi.name,  # type: ignore[union-attr]
                                         error=type(e).__name__)
            elif self.cloud_marathi is not None and self.audit:
                self.audit.write("voice_cloud_tts_blocked", reason=note)
        if self.local is None:
            raise VoiceUnavailable("no local voice on this platform (Windows and macOS only)")
        pb = self.local.speak(say, lang)
        self._log(self.local.name, False, lang, say)
        return SpeakResult(pb, self.local.name, False, note)

    def _log(self, engine: str, cloud: bool, lang: str, text: str) -> None:
        if self.audit:
            self.audit.write("voice_tts", engine=engine, cloud=cloud, language=lang, chars=len(text))


def local_engine_name(cfg: dict[str, Any], platform: str = sys.platform) -> str | None:
    engine = cfg.get("tts", {}).get("engine", "auto")
    if engine != "auto":
        return engine
    return {"win32": "windows_sapi", "darwin": "mac_say"}.get(platform)


def make_local_tts(cfg: dict[str, Any], platform: str = sys.platform, popen: Popen = subprocess.Popen):
    tts = cfg.get("tts", {})
    name = local_engine_name(cfg, platform)
    if name == "windows_sapi":
        return WindowsSapiTTS(tts.get("voice", ""), tts.get("rate", 0), popen)
    if name == "mac_say":
        return MacSayTTS(tts.get("voice", ""), tts.get("rate", 0), popen)
    if name == "fake":
        return FakeTTS()
    if name is None:
        return None
    raise ValueError(f"unknown tts engine {name!r}")


def make_speech(cfg: dict[str, Any], home: Path, audit: AuditLog | None = None, platform: str = sys.platform,
                popen: Popen = subprocess.Popen, force_cloud: bool | None = None) -> SpeechOutput:
    marathi = cfg.get("tts", {}).get("marathi", {})
    enabled = marathi.get("cloud_enabled", False) if force_cloud is None else force_cloud
    cloud = None
    if enabled and marathi.get("engine", "edge_tts") == "edge_tts":
        cloud = EdgeTTS(marathi.get("voice", "mr-IN-ManoharNeural"), home / "data" / "voice" / "tmp", popen,
                        platform=platform)
    return SpeechOutput(make_local_tts(cfg, platform, popen), cloud, marathi.get("max_privacy", "P1"), audit)
