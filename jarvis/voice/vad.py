"""Voice activity: a simple energy detector, and barge-in (stop speaking when the user talks).

The energy detector needs no model. Without echo cancellation, Jarvis's own voice from the
speakers can trigger it, so `barge_in: voice` is meant for headphones; `barge_in: key`
(press Enter) always works. A model-based VAD (Silero, bundled with faster-whisper as ONNX)
can replace EnergyVAD behind the same `is_speech` call later.
"""

from __future__ import annotations

import threading
from typing import Any, Callable

from jarvis.control.stop import StopSwitch
from jarvis.voice.base import SAMPLE_RATE, Playback, rms


class EnergyVAD:
    def __init__(self, threshold_rms: float = 900, min_speech_ms: int = 240, sample_rate: int = SAMPLE_RATE):
        self.threshold = threshold_rms
        self.min_speech_ms = min_speech_ms
        self.sample_rate = sample_rate
        self._speech_ms = 0

    def is_speech(self, frame: bytes) -> bool:
        return rms(frame) >= self.threshold

    def feed(self, frame: bytes) -> bool:
        """True once speech has lasted min_speech_ms without a break."""
        ms = len(frame) // 2 * 1000 // self.sample_rate
        self._speech_ms = self._speech_ms + ms if self.is_speech(frame) else 0
        return self._speech_ms >= self.min_speech_ms

    def reset(self) -> None:
        self._speech_ms = 0


class PlaybackGuard:
    """While Jarvis speaks: stop on emergency stop, and (optionally) when the user starts talking."""

    def __init__(self, playback: Playback, stop_switch: StopSwitch, recorder: Any = None,
                 vad: EnergyVAD | None = None, poll_seconds: float = 0.2,
                 on_barge_in: Callable[[], None] | None = None):
        self.playback = playback
        self.stop_switch = stop_switch
        self.recorder = recorder
        self.vad = vad
        self.poll = poll_seconds
        self.on_barge_in = on_barge_in
        self.barged_in = False
        self.emergency = False
        self._done = threading.Event()
        self._threads: list[threading.Thread] = []

    def start(self) -> "PlaybackGuard":
        self._threads.append(threading.Thread(target=self._watch_stop, daemon=True))
        if self.recorder is not None and self.vad is not None:
            self._threads.append(threading.Thread(target=self._watch_mic, daemon=True))
        for t in self._threads:
            t.start()
        return self

    def _watch_stop(self) -> None:
        while not self._done.is_set() and self.playback.is_playing():
            if self.stop_switch.engaged():
                self.emergency = True
                self.playback.stop()
                break
            self._done.wait(self.poll)

    def _watch_mic(self) -> None:
        self.vad.reset()  # type: ignore[union-attr]

        def on_frame(frame: bytes) -> bool:
            if self._done.is_set() or not self.playback.is_playing():
                return True
            if self.vad.feed(frame):  # type: ignore[union-attr]
                self.barged_in = True
                self.playback.stop()
                if self.on_barge_in:
                    self.on_barge_in()
                return True
            return False

        try:
            self.recorder.listen(on_frame, stop=self._done)  # type: ignore[union-attr]
        except Exception:  # a busy or missing microphone must not break speaking
            pass

    def close(self, timeout: float = 1.0) -> None:
        self._done.set()
        for t in self._threads:
            t.join(timeout)
