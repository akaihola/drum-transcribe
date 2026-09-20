# drum-transcribe

Forensic drum-set transcription: recording in, drum sheet music out, with
every intermediate step saved for inspection and manual correction.

## Pipeline

| stage | tool | artifact |
|---|---|---|
| 1. drum stem separation | [Demucs] (htdemucs) | `stems/htdemucs/<song>/drums.wav` |
| 2. beat/downbeat tracking | [beat_this] | `beats.json` |
| 3. drum hit detection | [ADTOF-pytorch] (kick/snare/tom/hihat/cymbal) | `onsets.json` |
| 4. velocity estimation | band-limited stem energy per hit | (merged into `onsets.json`) |
| 5. grid quantization | per-beat subdivision fit (16ths/32nds/triplets) | `events.json` |
| 6. rendering | [music21] → MusicXML; [pretty_midi] → audition MIDI | `score.musicxml`, `audition.mid` |

[Demucs]: https://github.com/adefossez/demucs
[beat_this]: https://github.com/CPJKU/beat_this
[ADTOF-pytorch]: https://github.com/xavriley/ADTOF-pytorch
[music21]: https://github.com/cuthbertLab/music21
[pretty_midi]: https://github.com/craffel/pretty-midi

## Usage

```bash
uv sync
uv run drum-transcribe run song.mp3 -o output/song --title "Song (drums)"
```

Open `score.musicxml` in MuseScore Studio for cleanup; play `audition.mid`
against the original recording to hear detection/quantization errors.
`events.json` records per-event quantization error (ms) and model confidence
for QA. Runs CPU-only; no GPU needed for single songs.

Everything is forensic-first: no rhythmic simplification, per-beat triplet vs.
straight subdivision choice, ghost notes kept (parenthesized snare noteheads
below velocity 45).

## Notes

- ADTOF model weights are CC BY-NC (non-commercial).
- Known ADT limits (see `docs/adt-landscape.md`): toms and cymbal classes are
  the least reliable; open/closed hi-hat, flams, and chokes are not detected.
- The 5-class model can't tell ride from crash or open from closed hi-hat; a
  future 6-stem separation stage (MDX23C DrumSep) could refine that.
