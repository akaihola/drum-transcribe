"""Stage 2: beat/downbeat tracking with beat_this -> bar/beat grid."""

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass
class BeatGrid:
    """Beat times (s) and, for each beat, its 1-based position within its bar."""

    times: np.ndarray  # beat instants, seconds
    positions: np.ndarray  # 1 = downbeat, 2, 3, ...

    @property
    def meter(self) -> int:
        """Most common number of beats per bar."""
        downbeat_idx = np.flatnonzero(self.positions == 1)
        bar_lengths = np.diff(downbeat_idx)
        if len(bar_lengths) == 0:
            return int(self.positions.max()) or 4
        values, counts = np.unique(bar_lengths, return_counts=True)
        return int(values[np.argmax(counts)])

    def save(self, path: Path) -> None:
        path.write_text(
            json.dumps(
                {"times": self.times.tolist(), "positions": self.positions.tolist()},
                indent=1,
            )
        )

    @classmethod
    def load(cls, path: Path) -> "BeatGrid":
        d = json.loads(path.read_text())
        return cls(np.asarray(d["times"]), np.asarray(d["positions"]))


def regularize(grid: BeatGrid) -> BeatGrid:
    """Repair tracker slips, assuming a steady tempo and a constant meter.

    Walks the dominant pulse through the raw beats: keeps each raw beat that
    lands near the expected next pulse, drops inserted extras (e.g. bursts of
    doubled tempo), and keeps the pulse going through holes. Then re-lays the
    barlines every `meter` beats on the phase that agrees with the most
    detected downbeats. The web UI's keep-raw-bars flag bypasses this for
    pieces whose uneven bars are real.
    """
    raw = grid.times.astype(float)
    meter = grid.meter
    if len(raw) < 8 or meter < 2:
        return grid
    ibi = float(np.median(np.diff(raw)))
    tol = 0.3 * ibi
    times = [raw[0]]
    j = 1
    while j < len(raw):
        target = times[-1] + ibi
        while j < len(raw) and raw[j] < target - tol:
            j += 1  # inserted extra beat: drop it
        if j < len(raw) and abs(raw[j] - target) <= tol:
            times.append(raw[j])  # re-lock onto the tracker
            j += 1
        else:
            times.append(target)  # missing beat: keep the pulse going
    times = np.asarray(times)

    # Barline phase = the one most raw downbeats (mapped to the cleaned
    # pulse) agree with.
    raw_downbeats = grid.times[grid.positions == 1]
    idx = np.searchsorted(times, raw_downbeats)
    idx = np.clip(idx, 1, len(times) - 1)
    idx -= raw_downbeats - times[idx - 1] < times[idx] - raw_downbeats
    values, counts = np.unique(idx % meter, return_counts=True)
    phase = int(values[np.argmax(counts)])
    positions = (np.arange(len(times)) - phase) % meter + 1
    return BeatGrid(times=times, positions=positions)


def track_beats(audio: Path, device: str = "cpu") -> BeatGrid:
    """Run beat_this on the (full-mix) audio; return the beat grid."""
    from beat_this.inference import File2Beats

    f2b = File2Beats(checkpoint_path="final0", device=device, dbn=False)
    beats, downbeats = f2b(str(audio))
    beats = np.asarray(beats)
    downbeats = np.asarray(downbeats)
    positions = np.zeros(len(beats), dtype=int)
    bar_start_idx = np.searchsorted(beats, downbeats)
    pos = 1
    j = 0
    for i in range(len(beats)):
        if j < len(bar_start_idx) and i == bar_start_idx[j]:
            pos = 1
            j += 1
        positions[i] = pos
        pos += 1
    return BeatGrid(times=beats, positions=positions)
