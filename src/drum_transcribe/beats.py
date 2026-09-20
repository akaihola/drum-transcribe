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
