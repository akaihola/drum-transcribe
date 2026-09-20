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

# Displayed note lengths are snapped down to conventional values (straight
# vs. triplet family by grid position); arbitrary gap fractions like 5/6
# produce tuplets (e.g. 6:5) that MuseScore refuses to import.
STRAIGHT_QL = [Fraction(1), Fraction(3, 4), Fraction(1, 2), Fraction(3, 8),
               Fraction(1, 4), Fraction(1, 8), Fraction(1, 16)]
TRIPLET_QL = [Fraction(2, 3), Fraction(1, 3), Fraction(1, 6), Fraction(1, 12)]


def _display_ql(pos: Fraction, gap: Fraction) -> Fraction:
    allowed = TRIPLET_QL if pos.denominator % 3 == 0 else STRAIGHT_QL
    for ql in allowed:
        if ql <= gap:
            return ql
    return gap  # tiny straight->triplet transition gap; keep it exact


def events_to_score(events: list[Event], meter: int, title: str = ""):
    """Build a one-staff percussion score; returns a music21 Score."""
    from music21 import clef, duration, instrument, metadata, note, percussion, stream
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
        for voice_no in (1, 2):
            voice = stream.Voice(id=str(voice_no))
            # group simultaneous hits into chords
            slots: dict[Fraction, list[Event]] = {}
            for e in bar_events:
                if STAFF[e.instrument][2] == voice_no:
                    slots.setdefault(e.beat, []).append(e)
            positions = sorted(slots)
            for i, pos in enumerate(positions):
                nxt = positions[i + 1] if i + 1 < len(positions) else Fraction(meter)
                ql = _display_ql(pos, Fraction(nxt - pos))
                notes = []
                for e in slots[pos]:
                    display, head, _v = STAFF[e.instrument]
                    n = note.Unpitched(displayName=display)
                    n.notehead = head
                    n.volume.velocity = e.velocity
                    if e.instrument == "snare" and e.velocity <= GHOST_VELOCITY:
                        n.noteheadParenthesis = True
                    notes.append(n)
                obj = notes[0] if len(notes) == 1 else percussion.PercussionChord(notes)
                obj.duration = duration.Duration(ql)
                voice.insert(float(pos), obj)
            if voice.notes:
                voice.makeRests(refStreamOrTimeRange=[0.0, float(meter)], fillGaps=True, inPlace=True)
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
    score = score.makeNotation(inPlace=False)
    score.write("musicxml", fp=str(path))
    return path
