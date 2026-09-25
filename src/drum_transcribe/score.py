"""Stage 5: render quantized events as a drum staff -> MusicXML (via music21)."""

from fractions import Fraction
from pathlib import Path

from .quantize import Event

# Standard drum-set staff positions (percussion clef) and noteheads.
STAFF = {
    #             display  notehead  voice (1 = hands/stems up, 2 = feet/stems down)
    "kick": ("F4", "normal", 2),
    "snare": ("C5", "normal", 1),
    "tom": ("E5", "normal", 1),
    "hihat": ("G5", "x", 1),
    "ride": ("F5", "x", 1),
    "crash": ("A5", "x", 1),
    "cymbal": ("A5", "x", 1),  # ADTOF's merged ride+crash class
}
GHOST_VELOCITY = 45  # snare hits at or below this get a parenthesized notehead

# Quantization picks ONE subdivision per beat (straight or triplet), so
# notation stays on that beat's grid and never crosses a beat boundary.
# Mixing the grids inside a beat is what produced the exotic tuplets
# (6:5, 24:17, 1/24 remainders) that MuseScore refuses to import.
STRAIGHT_QL = [Fraction(1), Fraction(3, 4), Fraction(1, 2), Fraction(3, 8),
               Fraction(1, 4), Fraction(1, 8), Fraction(1, 16)]
TRIPLET_QL = [Fraction(2, 3), Fraction(1, 3), Fraction(1, 6), Fraction(1, 12)]


def _beat_families(events: list[Event]) -> dict[int, bool]:
    """Which beats of a bar are on the triplet grid (by event positions)."""
    fams: dict[int, bool] = {}
    for e in events:
        beat = int(e.beat)
        fams[beat] = fams.get(beat, False) or e.beat.denominator % 3 == 0
    return fams


def _fit_ql(at: Fraction, until: Fraction, fams: dict[int, bool]) -> Fraction:
    """Largest conventional length from `at`, capped at the beat boundary."""
    limit = min(until, Fraction(int(at) + 1)) - at
    allowed = TRIPLET_QL if fams.get(int(at), False) else STRAIGHT_QL
    return next((d for d in allowed if d <= limit), limit)


def _rest_steps(a: Fraction, b: Fraction, fams: dict[int, bool]):
    while a < b:
        step = _fit_ql(a, b, fams)
        yield a, step
        a += step


def _duration(ql: Fraction):
    """Triplet lengths all count in eighth-note triplets (3:2, one beat).

    Left to itself music21 gives a 2/3 its own quarter-triplet and a 1/6 a
    16th-triplet; a beat mixing them never completes either tuplet, so no
    brackets get written and MuseScore guesses wrong groups -> an overfull
    bar ("Found: 49/48"), which its CLI refuses to load."""
    from music21 import duration

    if ql not in TRIPLET_QL:
        return duration.Duration(ql)
    d = duration.Duration(ql * Fraction(3, 2))
    d.appendTuplet(duration.Tuplet(3, 2, "eighth"))
    return d


def events_to_score(events: list[Event], meter: int, title: str = ""):
    """Build a one-staff percussion score; returns a music21 Score."""
    from music21 import clef, instrument, metadata, note, percussion, stream
    from music21 import meter as m21meter

    n_bars = max((e.bar for e in events), default=1)
    # Start from bar 1 (or a pickup bar 0) even if the drums enter later, so
    # bar numbers stay aligned with the recording.
    first_bar = min(1, *(e.bar for e in events)) if events else 1
    by_bar: dict[int, list[Event]] = {}
    for e in events:
        by_bar.setdefault(e.bar, []).append(e)

    part = stream.Part()
    part.insert(0, instrument.UnpitchedPercussion())

    for bar_no in range(first_bar, n_bars + 1):
        m = stream.Measure(number=bar_no)
        if bar_no == first_bar:
            m.insert(0, clef.PercussionClef())
            m.insert(0, m21meter.TimeSignature(f"{meter}/4"))
        bar_events = by_bar.get(bar_no, [])
        fams = _beat_families(bar_events)
        for voice_no in (1, 2):
            voice = stream.Voice(id=str(voice_no))
            # group simultaneous hits into chords
            slots: dict[Fraction, list[Event]] = {}
            for e in bar_events:
                if STAFF[e.instrument][2] == voice_no:
                    slots.setdefault(e.beat, []).append(e)
            # Hits closer than 1/12 beat (adjacent straight vs. triplet grid
            # slots) are one chord to a reader; keeping them apart produces
            # unreadable fragments (12:7 tuplets, 128th rests) that MuseScore
            # also rejects.
            positions = []
            for pos in sorted(slots):
                if positions and pos - positions[-1] < Fraction(1, 12):
                    slots[positions[-1]].extend(slots.pop(pos))
                else:
                    positions.append(pos)
            cursor = Fraction(0)
            for i, pos in enumerate(positions):
                nxt = positions[i + 1] if i + 1 < len(positions) else Fraction(meter)
                ql = _fit_ql(pos, nxt, fams)
                notes = []
                by_instrument: dict[str, Event] = {}
                for e in slots[pos]:  # merged duplicates: keep the louder hit
                    if (prev := by_instrument.get(e.instrument)) is None or e.velocity > prev.velocity:
                        by_instrument[e.instrument] = e
                for e in by_instrument.values():
                    display, head, _v = STAFF[e.instrument]
                    n = note.Unpitched(displayName=display)
                    n.notehead = head
                    n.volume.velocity = e.velocity
                    if e.instrument == "snare" and e.velocity <= GHOST_VELOCITY:
                        n.noteheadParenthesis = True
                    notes.append(n)
                obj = notes[0] if len(notes) == 1 else percussion.PercussionChord(notes)
                obj.duration = _duration(ql)
                for at, step in _rest_steps(cursor, pos, fams):
                    voice.insert(at, note.Rest(duration=_duration(step)))
                voice.insert(pos, obj)
                cursor = pos + ql
            if voice.notes:
                for at, step in _rest_steps(cursor, Fraction(meter), fams):
                    voice.insert(at, note.Rest(duration=_duration(step)))
                m.insert(0, voice)
        if not m.voices:
            m.insert(0, note.Rest(quarterLength=meter))
        part.append(m)

    score = stream.Score()
    if title:
        score.metadata = metadata.Metadata(title=title)
    score.append(part)
    return score


def write_musicxml(events: list[Event], meter: int, path: Path, title: str = "") -> Path:
    score = events_to_score(events, meter, title)
    # makeNotation adds the explicit tuplet brackets MuseScore needs to
    # import mixed triplet runs. It only behaves because events_to_score
    # emits nothing but conventional, beat-aligned durations — fed anything
    # else it invents fragments (12:7 tuplets, 128th rests) MuseScore rejects.
    score = score.makeNotation(inPlace=False)
    score.write("musicxml", fp=str(path))
    return path
