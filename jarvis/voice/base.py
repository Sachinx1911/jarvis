"""Voice interfaces and shared types. No engine-specific imports here."""

from __future__ import annotations

import io
import math
import wave
from array import array
from dataclasses import dataclass
from typing import Callable, Protocol

SAMPLE_RATE = 16000  # Whisper and openWakeWord both expect 16 kHz mono 16-bit PCM


class VoiceUnavailable(RuntimeError):
    """An engine cannot run on this machine (missing package, model or OS feature).

    The message always says what to do next (e.g. "run `jarvis voice setup`").
    """


@dataclass(frozen=True)
class Audio:
    """Mono 16-bit little-endian PCM."""

    pcm: bytes
    sample_rate: int = SAMPLE_RATE

    @property
    def seconds(self) -> float:
        return len(self.pcm) / 2 / self.sample_rate

    def samples(self) -> array:
        a = array("h")
        a.frombytes(self.pcm[: len(self.pcm) // 2 * 2])
        return a

    def to_wav(self) -> bytes:
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(self.sample_rate)
            w.writeframes(self.pcm)
        return buf.getvalue()

    @staticmethod
    def from_wav(data: bytes) -> "Audio":
        with wave.open(io.BytesIO(data), "rb") as w:
            if w.getnchannels() != 1 or w.getsampwidth() != 2:
                raise ValueError("expected mono 16-bit WAV")
            return Audio(w.readframes(w.getnframes()), w.getframerate())


def rms(pcm: bytes) -> float:
    """Root-mean-square level of 16-bit PCM (0..32768). Pure Python: no numpy needed."""
    a = array("h")
    a.frombytes(pcm[: len(pcm) // 2 * 2])
    if not a:
        return 0.0
    return math.sqrt(sum(s * s for s in a) / len(a))


@dataclass(frozen=True)
class Transcript:
    text: str
    language: str | None  # ISO 639-1 code, e.g. "en", "mr"; None if unknown
    confidence: float  # 0..1; engines map their own scores onto this
    engine: str | None = None  # set by LanguageRouter: the engine that produced this text


class SpeechToText(Protocol):
    name: str

    def transcribe(self, audio: Audio, language_hint: str | None = None) -> Transcript: ...


class Playback(Protocol):
    """Speech that is playing. stop() must be safe to call at any time, more than once."""

    def is_playing(self) -> bool: ...

    def wait(self, timeout: float | None = None) -> bool: ...  # True once finished

    def stop(self) -> None: ...


class TextToSpeech(Protocol):
    name: str
    cloud: bool  # True if text leaves this machine

    def speak(self, text: str, language: str = "en") -> Playback: ...


FrameHandler = Callable[[bytes], bool]  # return True to stop listening


class Recorder(Protocol):
    sample_rate: int

    def record_push_to_talk(self) -> Audio: ...

    def listen(self, on_frame: FrameHandler, max_seconds: float | None = None) -> None: ...


class WakeWordDetector(Protocol):
    name: str

    def process(self, frame: bytes) -> bool: ...  # True when the wake word was heard

    def reset(self) -> None: ...


class DonePlayback:
    """A playback that has already finished (nothing to say, or an engine that blocks)."""

    def is_playing(self) -> bool:
        return False

    def wait(self, timeout: float | None = None) -> bool:
        return True

    def stop(self) -> None:
        pass
