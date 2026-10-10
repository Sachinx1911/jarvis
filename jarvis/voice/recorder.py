"""Microphone recording with sounddevice (PortAudio).

sounddevice ships PortAudio inside its Windows and macOS wheels, so nothing else is
installed; it is about 1 MB and needs only cffi. RawInputStream gives plain bytes, so
recording needs no numpy. https://python-sounddevice.readthedocs.io/

The `sd` module is injectable, so recording is tested with a fake device.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable

from jarvis.voice.base import SAMPLE_RATE, Audio, FrameHandler, VoiceUnavailable

FRAME_MS = 80  # openWakeWord's preferred chunk (1280 samples at 16 kHz)
PACKAGE_HINT = "pip install sounddevice==0.5.6"


def import_sounddevice() -> Any:
    try:
        import sounddevice
    except (ImportError, OSError) as e:  # OSError: PortAudio library not found
        raise VoiceUnavailable(f"microphone support is not installed: {PACKAGE_HINT}") from e
    return sounddevice


class SoundDeviceRecorder:
    def __init__(self, wait_for_stop: Callable[[], None], sample_rate: int = SAMPLE_RATE, device: Any = None,
                 max_seconds: float = 30, sd: Any = None):
        """wait_for_stop blocks until the user ends a push-to-talk recording (e.g. presses Enter)."""
        self.wait_for_stop = wait_for_stop
        self.sample_rate = sample_rate
        self.device = device
        self.max_seconds = max_seconds
        self._sd = sd

    @property
    def sd(self) -> Any:
        if self._sd is None:
            self._sd = import_sounddevice()
        return self._sd

    def _stream(self, callback: Callable[..., None]) -> Any:
        return self.sd.RawInputStream(samplerate=self.sample_rate, blocksize=self.sample_rate * FRAME_MS // 1000,
                                      device=self.device, channels=1, dtype="int16", callback=callback)

    def record_push_to_talk(self) -> Audio:
        """Record from now until wait_for_stop() returns. Audio past max_seconds is dropped."""
        chunks: list[bytes] = []
        limit = int(self.max_seconds * self.sample_rate * 2)
        size = 0

        def callback(indata, frames, t, status) -> None:
            nonlocal size
            if size < limit:
                data = bytes(indata)[: limit - size]
                chunks.append(data)
                size += len(data)

        with self._stream(callback):
            self.wait_for_stop()
        return Audio(b"".join(chunks), self.sample_rate)

    def listen(self, on_frame: FrameHandler, max_seconds: float | None = None,
               stop: threading.Event | None = None) -> None:
        """Feed each ~80 ms frame to on_frame until it returns True, `stop` is set, or time runs out."""
        done = stop or threading.Event()

        def callback(indata, frames, t, status) -> None:
            if not done.is_set() and on_frame(bytes(indata)):
                done.set()

        with self._stream(callback):
            done.wait(max_seconds)
        done.set()

    def record_utterance(self, is_speech: Callable[[bytes], bool], end_silence_ms: int = 900,
                         max_seconds: float | None = None) -> Audio:
        """Record until speech has started and then `end_silence_ms` of silence follows (wake-word mode)."""
        chunks: list[bytes] = []
        state = {"spoken": False, "silent_ms": 0}

        def on_frame(frame: bytes) -> bool:
            chunks.append(frame)
            ms = len(frame) // 2 * 1000 // self.sample_rate
            if is_speech(frame):
                state["spoken"], state["silent_ms"] = True, 0
            else:
                state["silent_ms"] += ms
            return state["spoken"] and state["silent_ms"] >= end_silence_ms

        self.listen(on_frame, max_seconds or self.max_seconds)
        return Audio(b"".join(chunks), self.sample_rate)


class FakeRecorder:
    """Test double: returns prepared audio; listen() replays prepared frames."""

    def __init__(self, recordings: list[Audio] | None = None, frames: list[bytes] | None = None,
                 sample_rate: int = SAMPLE_RATE):
        self.recordings = list(recordings or [])
        self.frames = list(frames or [])
        self.sample_rate = sample_rate
        self.recorded = 0

    def record_push_to_talk(self) -> Audio:
        self.recorded += 1
        return self.recordings.pop(0) if self.recordings else Audio(b"", self.sample_rate)

    def listen(self, on_frame: FrameHandler, max_seconds: float | None = None,
               stop: threading.Event | None = None) -> None:
        for frame in self.frames:
            if (stop and stop.is_set()) or on_frame(frame):
                return

    def record_utterance(self, is_speech: Callable[[bytes], bool], end_silence_ms: int = 900,
                         max_seconds: float | None = None) -> Audio:
        return self.record_push_to_talk()


class FakeSoundDevice:
    """Stands in for the sounddevice module: the stream calls back with prepared frames."""

    def __init__(self, frames: list[bytes], devices: list[dict] | None = None):
        self.frames = frames
        self.opened: list[dict] = []
        self.devices = devices or []

    def RawInputStream(self, **kwargs):  # noqa: N802 (mirrors the sounddevice API)
        self.opened.append(kwargs)
        frames = self.frames
        callback = kwargs["callback"]

        class _Stream:
            def __enter__(self_inner):
                def feed():
                    for f in frames:
                        callback(f, len(f) // 2, None, None)
                        time.sleep(0)
                self_inner.thread = threading.Thread(target=feed, daemon=True)
                self_inner.thread.start()
                self_inner.thread.join()
                return self_inner

            def __exit__(self_inner, *exc):
                return False

        return _Stream()

    def query_devices(self):
        return self.devices


def list_devices(sd: Any = None) -> list[dict]:
    sd = sd or import_sounddevice()
    out = []
    for i, d in enumerate(sd.query_devices()):
        out.append({"index": i, "name": d["name"], "inputs": d["max_input_channels"],
                    "outputs": d["max_output_channels"]})
    return out
