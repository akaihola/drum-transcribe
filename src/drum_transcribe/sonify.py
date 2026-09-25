"""Mix synthetic percussion blips over the original audio for by-ear QA.

Each instrument gets an easily distinguishable synthetic sound; velocities
scale amplitude. Listening to this against the original exposes missed,
spurious, and misclassified hits far faster than reading the score.
"""

from pathlib import Path

import numpy as np

from .quantize import Event

SR = 48000  # Opus only takes 48 kHz (or lower rates)


def _blip(freq: float, dur: float, noise: float = 0.0, hp: bool = False) -> np.ndarray:
    n = int(SR * dur)
    t = np.arange(n) / SR
    env = np.exp(-t * 30 / dur / 4)
    sig = np.sin(2 * np.pi * freq * t)
    if noise:
        rng = np.random.default_rng(0)
        white = rng.standard_normal(n)
        if hp:  # crude high-pass: differentiate
            white = np.diff(white, prepend=0.0)
        sig = (1 - noise) * sig + noise * white
    return (sig * env).astype(np.float32)


SOUNDS = {
    "kick": _blip(80, 0.10),
    "snare": _blip(240, 0.12, noise=0.7),
    "tom": _blip(140, 0.15),
    "hihat": _blip(6000, 0.05, noise=0.9, hp=True),
    "ride": _blip(5200, 0.30, noise=0.4, hp=True),
    "crash": _blip(4000, 0.45, noise=0.9, hp=True),
    "cymbal": _blip(4500, 0.25, noise=0.8, hp=True),
}


def write_sonification(
    events: list[Event], original: Path, out: Path, blip_gain: float = 0.9
) -> Path:
    import librosa
    import soundfile as sf

    y, _sr = librosa.load(str(original), sr=SR, mono=True)
    end = max((e.time for e in events), default=0.0) + 1.0
    mix = np.zeros(max(len(y), int(end * SR)), dtype=np.float32)
    mix[: len(y)] = y * 0.5
    for e in events:
        s = SOUNDS[e.instrument] * (e.velocity / 127) * blip_gain
        i = int(e.time * SR)
        mix[i : i + len(s)] += s[: max(0, len(mix) - i)]
    peak = np.abs(mix).max()
    if peak > 1:
        mix /= peak
    # Opus at ~110 kbps: ~12x smaller than WAV, and unlike MP3 no start delay
    # to throw playback out of step with the score
    sf.write(str(out), mix, SR, format="OGG", subtype="OPUS", compression_level=0.6)
    return out
