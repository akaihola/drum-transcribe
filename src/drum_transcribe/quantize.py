"""Stage 4: snap detected onsets onto the bar/beat grid.

Forensic goal: preserve exactly what was played. Each beat independently picks
the subdivision (16ths, 32nds, or triplets) that best explains its onsets, so
straight and triplet feels can coexist. Quantization error is recorded per
event for later QA.
"""

import json
from dataclasses import asdict, dataclass
from fractions import Fraction
from pathlib import Path

import numpy as np

from .beats import BeatGrid
from .transcribe import Onset

# Candidate subdivisions of one beat; ties go to the earlier (simpler) entry.
SUBDIVISIONS = [2, 4, 3, 6, 8]


@dataclass
class Event:
    bar: int  # 1-based bar number
    beat: Fraction  # position within bar, in beats from 0 (e.g. 3/2 = "and of 2")
    instrument: str
    velocity: int
    confidence: float
    error_ms: float  # onset time minus chosen grid point
    time: float  # quantized position mapped back to seconds (for audition MIDI)


def save_events(events: list[Event], meter: int, path: Path) -> None:
    payload = {
        "meter": meter,
        "events": [
            {**asdict(e), "beat": [e.beat.numerator, e.beat.denominator]}
            for e in events
        ],
    }
    path.write_text(json.dumps(payload, indent=1))


def load_events(path: Path) -> tuple[list[Event], int]:
    d = json.loads(path.read_text())
    events = []
    for e in d["events"]:
        kwargs = dict(e)
        kwargs["beat"] = Fraction(e["beat"][0], e["beat"][1])
        events.append(Event(**kwargs))
    return events, d["meter"]


def _extend_grid(grid: BeatGrid, until: float) -> tuple[np.ndarray, np.ndarray, int]:
    """Pad the beat grid at both ends so every onset falls inside it.

    Returns the number of beats prepended too: any position-1 beat among them
    is an artifact of the padding arithmetic, and counting it as a downbeat
    would shift every bar number by one against the stored grid (which the
    web app counts bars from)."""
    times = grid.times.astype(float).tolist()
    positions = grid.positions.astype(int).tolist()
    ibi = float(np.median(np.diff(grid.times)))
    meter = grid.meter
    while times[-1] < until + ibi:
        times.append(times[-1] + ibi)
        positions.append(positions[-1] % meter + 1)
    n_front = 0
    while times[0] > 0:
        times.insert(0, times[0] - ibi)
        positions.insert(0, (positions[0] - 2) % meter + 1)
        n_front += 1
    return np.asarray(times), np.asarray(positions), n_front


def quantize(onsets: list[Onset], grid: BeatGrid) -> list[Event]:
    if not onsets:
        return []
    times, positions, n_front = _extend_grid(grid, max(o.time for o in onsets))
    meter = grid.meter

    # Group onsets by the beat interval they fall into.
    by_beat: dict[int, list[Onset]] = {}
    for o in onsets:
        i = int(np.searchsorted(times, o.time, side="right") - 1)
        i = max(0, min(i, len(times) - 2))
        by_beat.setdefault(i, []).append(o)

    # Bar numbering: count downbeats at or before each beat index.
    # Beats before the first downbeat (a pickup) get bar 0.
    is_downbeat = positions == 1
    is_downbeat[:n_front] = False
    bar_no = np.cumsum(is_downbeat)

    events = []
    for i, group in sorted(by_beat.items()):
        t0, t1 = times[i], times[i + 1]
        span = t1 - t0
        rel = np.array([(o.time - t0) / span for o in group])  # 0..1 within beat
        div, slots, best_cost = SUBDIVISIONS[0], np.round(rel * SUBDIVISIONS[0]), np.inf
        for cand in SUBDIVISIONS:
            cand_slots = np.round(rel * cand)
            cost = float(np.abs(rel - cand_slots / cand).sum())
            if cost < best_cost - 1e-9:
                div, slots, best_cost = cand, cand_slots, cost
        for o, slot, r in zip(group, slots, rel):
            frac = Fraction(int(slot), div)
            beat_pos = positions[i] - 1 + frac  # 0-based within bar
            bar = int(bar_no[i])
            if beat_pos >= meter:  # rounded up into the next beat/bar
                beat_pos -= meter
                bar += 1
            events.append(
                Event(
                    bar=bar,
                    beat=Fraction(beat_pos),
                    instrument=o.instrument,
                    velocity=o.velocity,
                    confidence=o.confidence,
                    error_ms=round(float((r - slot / div) * span * 1000), 1),
                    time=round(float(t0 + slot / div * span), 4),
                )
            )
    events.sort(key=lambda e: (e.bar, e.beat))
    return events
