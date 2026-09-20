# drum-transcribe

Turns a music recording into drum sheet music, automatically. Every
intermediate result is saved so mistakes can be found, heard, and fixed.

## What it does, step by step

1. **Isolate the drums.** A neural network (Demucs) separates the drum kit
   from the rest of the music, producing a "drums stem" — the same recording
   with only the drums audible.
2. **Find the beat.** Another model (beat_this) marks every beat and every
   bar line (downbeat) in time, like a conductor tapping along.
3. **Detect the hits.** Each drum hit is located and named: kick, snare,
   tom, hi-hat, cymbal. Two alternative methods are available — see
   *Pipeline variants* below.
4. **Estimate loudness.** Each hit's strength becomes a MIDI velocity, so
   quiet "ghost notes" survive into the notation.
5. **Snap to the grid.** Hits are placed on the beat grid (16ths, 32nds, or
   triplets, chosen per beat). How far each hit had to move is recorded —
   large moves are a warning sign.
6. **Write the score.** The result is saved as MusicXML and, when MuseScore
   is available, as a ready MuseScore file (`score.mscz`).

## Pipeline variants

Results of different methods are kept side by side, never mixed:

- **adtof** — a neural network trained on real drum recordings reads the
  drums stem directly. Most accurate hit detection, but hears only 5
  categories (ride and crash cymbals are one "cymbal").
- **mdx23c** — the drums stem is first split further into six per-drum
  recordings (kick / snare / toms / hi-hat / ride / crash); hits are then
  detected in each one separately. Distinguishes ride from crash.

## What is the sonification?

`sonification.wav` is the original recording (at half volume) with a short
synthetic **blip added at every hit the computer transcribed**: a low thump
for kick, a noisy mid snap for snare, high ticks for hi-hat and cymbals.
Listening to it is the fastest way to check the transcription: a missing
blip = missed hit, a blip with no drum under it = false detection, the wrong
blip sound = wrong drum. No musical training needed.

## The review website

```bash
uv run drum-transcribe serve
```

Open `http://atom.crane-boa.ts.net:8765/` (or the machine's address) from any
of your machines. For every song you get:

- players for the **original**, the **drums stem**, and each variant's
  **sonification**;
- while any player plays, the **bar being heard is highlighted in red** in
  the scores and kept in view;
- **download links**: MuseScore file, MusicXML, MIDI, and the raw detection
  data (JSON);
- all variants' **scores rendered on the page** for direct comparison.

## Running a transcription

```bash
uv sync                                          # once, installs everything
uv run drum-transcribe run song.mp3              # adtof variant (default)
uv run drum-transcribe run song.mp3 --variant mdx23c
```

Results land in `output/<song>/<variant>/`. The source recording, beat grid
and drums stem are shared per song in `output/<song>/`. Everything runs on a
normal CPU; a 3-minute song takes ~3 minutes with adtof, while mdx23c is
much slower (roughly 10× the song length).

## Honest limitations

Even the best available models mishear some things: toms are the weakest
category, hi-hat vs. ride gets confused, and flams, chokes, and open/closed
hi-hat are not detected at all. Every score needs a human check — that is
what the review website and the sonification are for. Details and the full
tool survey: `docs/adt-landscape.md`.

The ADTOF model weights are licensed for non-commercial use.
