"""Voice in the dashboard.

- The browser records with MediaRecorder, converts to 16 kHz mono 16-bit WAV itself (Web
  Audio API), and posts the raw WAV here. The existing speech-to-text engine
  (jarvis/voice/stt.py) transcribes it locally. If faster-whisper or its model is missing,
  the answer says so; nothing is downloaded.
- Audio is transcribed in memory and dropped (stored only if voice.yaml says store_audio).
- Low confidence returns "unclear" instead of guessing. The text goes into the chat box;
  Sachin sends it.
- "Speak reply" uses the existing SpeechOutput (local speakers). Its rules stay: P3 text is
  withheld from speech, and the cloud Marathi voice (off by default) never gets P2/P3 text.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from jarvis.web.context import WebContext

MAX_AUDIO_BYTES = 4 * 1024 * 1024   # 16 kHz mono 16-bit = 32 KB/s: about 2 minutes
NOT_INSTALLED = "speech-to-text not installed (run voice setup)"


def build_router(ctx: WebContext) -> APIRouter:
    r = APIRouter()

    def voice_cfg() -> dict[str, Any]:
        from jarvis.voice.config import load_voice_config

        return load_voice_config(ctx.config_dir)

    def stt_engine(home):
        if ctx.stt_factory is not None:
            return ctx.stt_factory()
        from jarvis.voice.stt import make_stt

        return make_stt(voice_cfg(), home)

    @r.get("/voice/status")
    def status() -> dict[str, Any]:
        """stt_ready / stt_detail / tts_engine: the microphone in Chat (unchanged). The rest, per
        part (English and Marathi speech-to-text, voices, wake word): see jarvis/voice/status.py.
        Only cheap checks: no model is loaded and nothing is downloaded."""
        from jarvis.voice.base import VoiceUnavailable
        from jarvis.voice.status import voice_status

        with ctx.runtime() as rt:
            home = rt.paths.home
        cfg = voice_cfg()
        stt = stt_engine(home)
        ready, detail = True, "ready"
        if hasattr(stt, "check"):
            try:
                stt.check()
            except VoiceUnavailable as e:
                ready, detail = False, f"{NOT_INSTALLED}: {e}"
        from jarvis.voice.tts import local_engine_name

        return {"stt_ready": ready, "stt_detail": detail, "tts_engine": local_engine_name(cfg),
                **voice_status(cfg, home)}

    def transcribe(data: bytes) -> dict[str, Any]:
        from jarvis.voice.base import Audio, VoiceUnavailable
        from jarvis.voice.stt import language_hint

        with ctx.runtime() as rt:
            home, audit = rt.paths.home, rt.audit
        cfg = voice_cfg()
        try:
            audio = Audio.from_wav(data)
        except Exception:
            raise HTTPException(400, "expected a mono 16-bit WAV recording")
        if audio.sample_rate != 16000:
            raise HTTPException(400, "expected 16 kHz audio")
        if audio.seconds < 0.2:
            return {"status": "no_audio", "text": ""}
        stt = stt_engine(home)
        try:
            if hasattr(stt, "check"):
                stt.check()
            t = stt.transcribe(audio, language_hint(cfg))
        except VoiceUnavailable as e:
            audit.write("voice_turn", source="dashboard", status="error", detail="stt_unavailable")
            raise HTTPException(503, f"{NOT_INSTALLED}: {e}")
        if cfg.get("store_audio", False):
            folder = home / "data" / "voice" / "recordings"
            folder.mkdir(parents=True, exist_ok=True)
            (folder / f"{datetime.now():%Y%m%d-%H%M%S}-dashboard.wav").write_bytes(audio.to_wav())
        min_conf = float(cfg["stt"].get("min_confidence", 0.45))
        status = "ok" if t.text.strip() and t.confidence >= min_conf else "unclear"
        audit.write("voice_turn", source="dashboard", status="transcribed" if status == "ok" else "unclear",
                    stt_engine=getattr(stt, "name", None), language=t.language, confidence=round(t.confidence, 3),
                    audio_seconds=round(audio.seconds, 2), heard_chars=len(t.text),
                    audio_stored=bool(cfg.get("store_audio", False)))
        return {"status": status, "text": t.text if status == "ok" else "", "heard": t.text,
                "language": t.language, "confidence": round(t.confidence, 3)}

    @r.post("/voice/transcribe")
    async def voice_transcribe(request: Request) -> dict[str, Any]:
        chunks, size = [], 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > MAX_AUDIO_BYTES:
                raise HTTPException(413, "the recording is too long")
            chunks.append(chunk)
        return await run_in_threadpool(transcribe, b"".join(chunks))

    return r


def speak_reply(ctx: WebContext, text: str) -> dict[str, Any]:
    """Speak a chat reply on this computer's speakers. Never blocks for the whole speech."""
    from jarvis.voice.base import VoiceUnavailable

    if ctx.stop.engaged():
        return {"spoken": False, "detail": "emergency stop is on"}
    try:
        if ctx.speech_factory is not None:
            speech = ctx.speech_factory()
        else:
            from jarvis.paths import default_paths
            from jarvis.voice.config import load_voice_config
            from jarvis.voice.tts import make_speech

            speech = make_speech(load_voice_config(ctx.config_dir), default_paths().home, ctx.audit)
        # P1 = an ordinary reply. SpeechOutput withholds P3 text and keeps P2+ off the cloud voice.
        res = speech.speak(text, sensitivity="P1")
    except VoiceUnavailable as e:
        return {"spoken": False, "detail": str(e)}
    except Exception as e:  # speech must never break the chat
        return {"spoken": False, "detail": f"voice output failed ({type(e).__name__})"}
    return {"spoken": True, "engine": res.engine, "cloud": res.cloud, "detail": res.note}
