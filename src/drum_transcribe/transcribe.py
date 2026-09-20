"""Stage 3: drum onset detection (ADTOF) + velocity estimation from the drums stem."""

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

# ADTOF class order; GM percussion numbers.
CLASSES = {35: "kick", 38: "snare", 47: "tom", 42: "hihat", 49: "cymbal"}
# Frequency bands (Hz) used to read per-class loudness off the drums stem.
BANDS = {
    "kick": (30, 150),
    "snare": (150, 1200),
    "tom": (80, 400),
    "hihat": (6000, 12000),
    "cymbal": (3000, 8000),
}


@dataclass
class Onset:
    time: float  # seconds
    instrument: str
    confidence: float  # ADTOF activation at the peak
    velocity: int  # 1-127, estimated from stem band energy


def save_onsets(onsets: list[Onset], path: Path) -> None:
    path.write_text(json.dumps([asdict(o) for o in onsets], indent=1))


def load_onsets(path: Path) -> list[Onset]:
    return [Onset(**d) for d in json.loads(path.read_text())]


def detect_onsets(audio: Path, device: str = "cpu") -> tuple[list[Onset], np.ndarray]:
    """Run ADTOF on `audio`; return onsets (velocity unset =100) and raw activations."""
    # transcribe_to_midi is annotated -> Path, but with return_activations=True
    # it actually returns the raw activation array.
    from typing import cast

    from adtof_pytorch import (
        FRAME_RNN_THRESHOLDS,
        LABELS_5,
        PeakPicker,
        transcribe_to_midi,
    )

    activations = cast(
        "np.ndarray",
        transcribe_to_midi(audio, "/dev/null", return_activations=True, device=device),
    )
    picker = PeakPicker(thresholds=FRAME_RNN_THRESHOLDS, fps=100)
    peaks = picker.pick(activations, labels=LABELS_5)[0]
    act = activations[0]  # [time, class]
    class_index = {label: i for i, label in enumerate(LABELS_5)}
    onsets = []
    for label, times in peaks.items():
        for t in times:
            frame = min(round(t * 100), act.shape[0] - 1)
            conf = float(act[frame, class_index[label]])
            onsets.append(Onset(t, CLASSES[label], round(conf, 3), 100))
    onsets.sort(key=lambda o: o.time)
    return onsets, act


CYMBALS = ("hihat", "ride", "crash")


def detect_onsets_from_stems(stems: dict[str, Path]) -> list[Onset]:
    """Per-drum onset detection on MDX23C stems (kick/snare/tom/hihat/ride/crash).

    The cymbal stems bleed into each other, so a hihat/ride/crash onset only
    counts for the stem that is loudest at that moment. Confidence is the
    envelope peak relative to the stem's loudest onset; velocity comes from
    the same peak on a dB scale (95th percentile -> 110).
    """
    import librosa

    hop = 256
    envs: dict[str, np.ndarray] = {}
    for instrument, stem in stems.items():
        y, sr = librosa.load(str(stem), sr=22050, mono=True)
        envs[instrument] = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop)

    onsets = []
    for instrument, env in envs.items():
        if env.max() <= 0:
            continue
        frames = librosa.onset.onset_detect(
            onset_envelope=env / env.max(), sr=22050, hop_length=hop,
            backtrack=False, delta=0.05, wait=2,
        )
        if instrument in CYMBALS:
            frames = [
                f for f in frames
                if all(env[f] >= envs[other][f] for other in CYMBALS if other != instrument)
            ]
        if len(frames) == 0:
            continue
        peaks = env[frames]
        ref = float(np.percentile(peaks, 95)) or 1.0
        for frame, peak in zip(frames, peaks):
            t = float(frame * hop / 22050)
            db = 10 * np.log10(max(float(peak), 1e-12) / ref)
            velocity = int(np.clip(round(110 + db * 2.5), 1, 127))
            confidence = round(float(peak) / float(env.max()), 3)
            onsets.append(Onset(t, instrument, confidence, velocity))
    onsets.sort(key=lambda o: o.time)
    return onsets


def estimate_velocities(onsets: list[Onset], drums_stem: Path) -> None:
    """Set each onset's velocity from band-limited energy of the drums stem.

    Per-instrument normalization: the 95th percentile of that instrument's
    onset energies maps to velocity 110; energy in dB below that scales down.
    """
    import librosa

    y, sr = librosa.load(str(drums_stem), sr=22050, mono=True)
    hop = 256
    S = np.abs(librosa.stft(y, n_fft=2048, hop_length=hop)) ** 2
    freqs = librosa.fft_frequencies(sr=sr, n_fft=2048)
    envelopes = {
        name: S[(freqs >= lo) & (freqs < hi), :].sum(axis=0)
        for name, (lo, hi) in BANDS.items()
    }
    n_frames = S.shape[1]
    energies: dict[str, list[tuple[Onset, float]]] = {}
    for o in onsets:
        center = round(o.time * sr / hop)
        lo = max(0, center - 2)
        hi = min(n_frames, center + 6)  # look ~70 ms past the onset
        e = float(envelopes[o.instrument][lo:hi].max()) if hi > lo else 0.0
        energies.setdefault(o.instrument, []).append((o, e))
    for pairs in energies.values():
        ref = np.percentile([e for _, e in pairs], 95) or 1.0
        for o, e in pairs:
            db = 10 * np.log10(max(e, 1e-12) / ref)  # <= ~0 for most hits
            o.velocity = int(np.clip(round(110 + db * 2.5), 1, 127))
