"""Small audio helpers for recordings that arrive from the dashboard or the Mac app.

The page sends plain 16-bit mono WAV at whatever rate the microphone runs (44.1 or 48 kHz).
Resampling and level normalisation happen here, on the server, so every client (Chrome, the
Mac app's WebKit view, a phone later) sends the same simple thing and gets the same result.
"""

from __future__ import annotations

from jarvis.voice.base import SAMPLE_RATE, Audio


def to_16k(audio: Audio) -> Audio:
    """The same audio at 16 kHz (what the speech models expect). Polyphase resampling with scipy
    when it is installed (it comes with the wake word package); linear interpolation otherwise."""
    if audio.sample_rate == SAMPLE_RATE:
        return audio
    import numpy as np  # installed with faster-whisper

    x = np.frombuffer(audio.pcm[: len(audio.pcm) // 2 * 2], dtype=np.int16).astype(np.float32)
    try:
        from math import gcd

        from scipy.signal import resample_poly

        g = gcd(SAMPLE_RATE, audio.sample_rate)
        y = resample_poly(x, SAMPLE_RATE // g, audio.sample_rate // g)
    except ImportError:
        n = int(round(len(x) * SAMPLE_RATE / audio.sample_rate))
        y = np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x)
    pcm = np.clip(y, -32768, 32767).astype("<i2").tobytes()
    return Audio(pcm, SAMPLE_RATE)


def normalize_peak(audio: Audio, target: float = 0.9, floor: float = 0.01, max_gain: float = 12.0) -> Audio:
    """Bring quiet speech up to a steady level (peak `target`). Near-silence stays as it is so
    background noise is not amplified; loud clips are left alone."""
    import numpy as np

    x = np.frombuffer(audio.pcm[: len(audio.pcm) // 2 * 2], dtype=np.int16).astype(np.float32) / 32768.0
    peak = float(np.abs(x).max()) if len(x) else 0.0
    if peak < floor or peak >= target:
        return audio
    y = x * min(target / peak, max_gain)
    return Audio((np.clip(y, -1.0, 1.0) * 32767).astype("<i2").tobytes(), audio.sample_rate)


def rms(audio: Audio) -> float:
    import numpy as np

    x = np.frombuffer(audio.pcm[: len(audio.pcm) // 2 * 2], dtype=np.int16).astype(np.float32) / 32768.0
    return float(np.sqrt((x ** 2).mean())) if len(x) else 0.0
