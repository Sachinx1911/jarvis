"""Server-side resampling and level normalisation for dashboard recordings."""

import math
import struct

import pytest

pytest.importorskip("numpy", reason="numpy comes with the optional [voice] extra")

from jarvis.voice.audio_tools import normalize_peak, rms, to_16k  # noqa: E402
from jarvis.voice.base import Audio


def sine(rate: int, seconds: float, hz: float = 440.0, amp: float = 0.3) -> Audio:
    n = int(rate * seconds)
    pcm = struct.pack(f"<{n}h", *[int(amp * 32767 * math.sin(2 * math.pi * hz * i / rate)) for i in range(n)])
    return Audio(pcm, rate)


def test_to_16k_keeps_duration_and_tone():
    a = to_16k(sine(48000, 1.0))
    assert a.sample_rate == 16000 and abs(a.seconds - 1.0) < 0.01
    assert abs(rms(a) - rms(sine(16000, 1.0))) < 0.02  # same loudness after resampling
    assert to_16k(sine(16000, 0.5)) .sample_rate == 16000


def test_normalize_peak_lifts_quiet_speech_but_not_silence():
    quiet = sine(16000, 0.5, amp=0.1)
    loud = normalize_peak(quiet)
    assert 0.85 <= max(abs(s) for s in loud.samples()) / 32767 <= 0.92
    silence = sine(16000, 0.5, amp=0.002)
    assert normalize_peak(silence).pcm == silence.pcm
    already = sine(16000, 0.5, amp=0.95)
    assert normalize_peak(already).pcm == already.pcm
