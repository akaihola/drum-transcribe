"""Render quantized events as a GM drum MIDI file for A/B listening checks."""

from pathlib import Path

from .quantize import Event

GM_NOTES = {
    "kick": 36,
    "snare": 38,
    "tom": 47,
    "hihat": 42,
    "ride": 51,
    "crash": 49,
    "cymbal": 49,
}


def write_audition_midi(events: list[Event], path: Path) -> Path:
    """Write events at their quantized real-time positions (grid seconds).

    Played alongside the original recording, this exposes both detection and
    quantization mistakes.
    """
    import pretty_midi

    midi = pretty_midi.PrettyMIDI()
    kit = pretty_midi.Instrument(program=0, is_drum=True, name="transcription")
    for e in events:
        kit.notes.append(
            pretty_midi.Note(
                velocity=e.velocity,
                pitch=GM_NOTES[e.instrument],
                start=e.time,
                end=e.time + 0.1,
            )
        )
    midi.instruments.append(kit)
    midi.write(str(path))
    return path
