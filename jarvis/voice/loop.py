"""Voice loop: push-to-talk -> speech-to-text -> ChatSession.send -> spoken reply.

- Press Enter to talk and Enter again to stop; or type a message instead.
- Barge-in: pressing Enter while Jarvis speaks stops the speech and starts listening.
  With `barge_in: voice`, speech picked up by the microphone also stops it.
- The emergency stop (jarvis stop, or saying "emergency stop") halts the turn and the speech.
- Every turn is audited with lengths, engines and timings only. Audio is not stored unless
  `store_audio: true`.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO

from jarvis.control.audit import AuditLog
from jarvis.control.stop import EmergencyStop, StopSwitch
from jarvis.paths import PROMPTS_DIR
from jarvis.providers.base import ProviderError
from jarvis.voice.approval import normalize
from jarvis.voice.base import Audio, Transcript, VoiceUnavailable
from jarvis.voice.tts import SpeechOutput
from jarvis.voice.vad import EnergyVAD, PlaybackGuard

EXIT_WORDS = {"/exit", "/quit", "exit", "quit"}
STOP_SPEAKING = {"stop", "jarvis stop", "stop jarvis", "be quiet", "thamb", "थांब", "थांबा"}
EMERGENCY = {"emergency stop", "jarvis emergency stop"}
REPEAT = "Sorry, I did not catch that. Please say it again."


def voice_style() -> str:
    path = PROMPTS_DIR / "voice.md"
    return path.read_text(encoding="utf-8").strip() if path.exists() else ""


class VoiceStyleContext:
    """Wraps the chat's context builder and adds the voice-mode instructions to the system prompt."""

    def __init__(self, inner: Any, style: str):
        self.inner = inner
        self.style = style

    def build(self, user_text: str, now: datetime):
        ctx = self.inner.build(user_text, now)
        if self.style:
            ctx.system = f"{ctx.system}\n\n{self.style}"
        return ctx

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)


@dataclass
class TurnResult:
    status: str  # replied | unclear | stopped_speaking | emergency_stop | error | no_audio
    heard: str = ""
    reply: str = ""
    tts_engine: str = ""
    cloud_tts: bool = False


class VoiceLoop:
    def __init__(self, session: Any, stt: Any, speech: SpeechOutput, recorder: Any, audit: AuditLog,
                 stop: StopSwitch, cfg: dict[str, Any], out: TextIO, inp: TextIO, home: Path,
                 wakeword: Any = None, mic_vad: EnergyVAD | None = None, language_hint: str | None = None):
        self.session = session
        self.stt = stt
        self.speech = speech
        self.recorder = recorder
        self.audit = audit
        self.stop = stop
        self.cfg = cfg
        self.out = out
        self.inp = inp
        self.home = home
        self.wakeword = wakeword
        self.mic_vad = mic_vad
        self.language_hint = language_hint
        self.min_confidence = float(cfg.get("stt", {}).get("min_confidence", 0.45))
        self.guard: PlaybackGuard | None = None
        self.turns = 0

    # ---- speaking ----

    def say(self, text: str, sensitivity: str = "P1") -> tuple[str, bool]:
        """Start speaking (non-blocking). Returns (engine, cloud)."""
        self.silence()
        try:
            res = self.speech.speak(text, sensitivity=sensitivity)
        except VoiceUnavailable as e:
            print(f"(voice output unavailable: {e})", file=self.out)
            return "", False
        if res.note:
            print(f"({res.note})", file=self.out)
        barge = self.cfg.get("barge_in", "key")
        voice_barge = barge == "voice" and self.mic_vad is not None
        self.guard = PlaybackGuard(res.playback, self.stop, self.recorder if voice_barge else None,
                                   self.mic_vad if voice_barge else None).start()
        return res.engine, res.cloud

    def silence(self) -> bool:
        """Stop any speech in progress. True if something was interrupted."""
        if self.guard is None:
            return False
        interrupted = self.guard.playback.is_playing()
        self.guard.playback.stop()
        self.guard.close()
        self.guard = None
        return interrupted

    def wait_speech(self, timeout: float | None = None) -> None:
        if self.guard is not None:
            self.guard.playback.wait(timeout)

    # ---- one turn ----

    def handle_audio(self, audio: Audio) -> TurnResult:
        t0 = time.monotonic()
        if self.cfg.get("store_audio", False) and audio.pcm:
            self._store(audio)
        if not audio.pcm:
            self._audit(TurnResult("no_audio"), None, t0, 0.0)
            return TurnResult("no_audio")
        try:
            transcript = self.stt.transcribe(audio, self.language_hint)
        except VoiceUnavailable as e:
            print(f"Speech-to-text unavailable: {e}", file=self.out)
            result = TurnResult("error")
            self._audit(result, None, t0, audio.seconds, detail="stt_unavailable")
            return result
        stt_ms = int((time.monotonic() - t0) * 1000)
        if not transcript.text.strip() or transcript.confidence < self.min_confidence:
            print(f"(heard {transcript.text!r}, confidence {transcript.confidence:.2f})", file=self.out)
            engine, cloud = self.say(REPEAT)
            result = TurnResult("unclear", transcript.text, REPEAT, engine, cloud)
            self._audit(result, transcript, t0, audio.seconds, stt_ms=stt_ms)
            return result
        print(f"You (voice): {transcript.text}", file=self.out)
        return self.handle_text(transcript.text, transcript, t0, audio.seconds, stt_ms)

    def handle_text(self, text: str, transcript: Transcript | None = None, t0: float | None = None,
                    audio_seconds: float = 0.0, stt_ms: int = 0) -> TurnResult:
        t0 = t0 if t0 is not None else time.monotonic()
        said = normalize(text)
        if said in EMERGENCY:
            self.silence()
            self.stop.engage("voice: emergency stop")
            self.audit.write("emergency_stop", reason="voice command")
            print("Emergency stop ON. Undo: jarvis resume", file=self.out)
            result = TurnResult("emergency_stop", text)
            self._audit(result, transcript, t0, audio_seconds, stt_ms=stt_ms)
            return result
        if said in STOP_SPEAKING:
            self.silence()
            result = TurnResult("stopped_speaking", text)
            self._audit(result, transcript, t0, audio_seconds, stt_ms=stt_ms)
            return result
        try:
            reply = self.session.send(text)
        except EmergencyStop as e:
            self.silence()
            print(f"Stopped: {e}", file=self.out)
            result = TurnResult("emergency_stop", text)
            self._audit(result, transcript, t0, audio_seconds, stt_ms=stt_ms)
            return result
        except ProviderError as e:
            print(f"Error ({e.kind}): {e}", file=self.out)
            result = TurnResult("error", text)
            self._audit(result, transcript, t0, audio_seconds, stt_ms=stt_ms, detail=e.kind)
            return result
        print(f"Jarvis: {reply}", file=self.out)
        engine, cloud = ("", False)
        if not self.stop.engaged():
            engine, cloud = self.say(reply)
        result = TurnResult("replied", text, reply, engine, cloud)
        self._audit(result, transcript, t0, audio_seconds, stt_ms=stt_ms)
        return result

    def _audit(self, r: TurnResult, t: Transcript | None, t0: float, audio_seconds: float,
               stt_ms: int = 0, detail: str = "") -> None:
        self.turns += 1
        self.audit.write(
            "voice_turn", session_id=getattr(self.session, "session_id", None), status=r.status,
            source="voice" if t is not None or audio_seconds else "typed",
            stt_engine=(t.engine or getattr(self.stt, "name", None)) if t is not None else None,
            language=t.language if t else None, confidence=round(t.confidence, 3) if t else None,
            audio_seconds=round(audio_seconds, 2), heard_chars=len(r.heard), reply_chars=len(r.reply),
            tts_engine=r.tts_engine or None, cloud_tts=r.cloud_tts, stt_ms=stt_ms,
            total_ms=int((time.monotonic() - t0) * 1000), audio_stored=bool(self.cfg.get("store_audio", False)),
            detail=detail or None,
        )

    def _store(self, audio: Audio) -> None:
        folder = self.home / "data" / "voice" / "recordings"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}.wav").write_bytes(audio.to_wav())

    # ---- the loop ----

    def _wait_for_wake_word(self) -> bool:
        assert self.wakeword is not None
        print("Listening for 'hey Jarvis'... (Ctrl+C to quit)", file=self.out)
        self.wakeword.reset()
        heard = {"yes": False}

        def on_frame(frame: bytes) -> bool:
            if self.stop.engaged():
                return True
            if self.wakeword.process(frame):
                heard["yes"] = True
                return True
            return False

        self.recorder.listen(on_frame)
        return heard["yes"]

    def run(self) -> int:
        if self.wakeword is not None:
            return self._run_wake_word()
        print("Voice mode. Press Enter to talk, Enter again to stop. Or type a message. /exit to quit.", file=self.out)
        while True:
            self.out.write("[Enter = talk] > ")
            self.out.flush()
            line = self.inp.readline()
            if not line:
                break
            interrupted = self.silence()  # barge-in by key
            if interrupted:
                self.audit.write("voice_barge_in", how="key")
            text = line.strip()
            if text.lower() in EXIT_WORDS:
                break
            if self.stop.engaged():
                print("Emergency stop is ON (jarvis resume to release).", file=self.out)
                continue
            if text:
                self.handle_text(text)
                continue
            print("Listening... press Enter when done.", file=self.out)
            try:
                audio = self.recorder.record_push_to_talk()
            except VoiceUnavailable as e:
                print(f"Microphone unavailable: {e}. Type your message instead.", file=self.out)
                continue
            self.handle_audio(audio)
        self.silence()
        return 0

    def _run_wake_word(self) -> int:
        vad = self.mic_vad or EnergyVAD()
        end_ms = int(self.cfg.get("vad", {}).get("end_silence_ms", 900))
        try:
            while not self.stop.engaged():
                if not self._wait_for_wake_word():
                    break
                self.silence()
                print("Yes?", file=self.out)
                audio = self.recorder.record_utterance(vad.is_speech, end_ms)
                self.handle_audio(audio)
                self.wait_speech()
        except KeyboardInterrupt:
            pass
        except VoiceUnavailable as e:
            print(f"Wake word unavailable: {e}", file=self.out)
            return 1
        self.silence()
        return 0
