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
  detected in each one separately. Distinguishes ride from crash, but
  hears too many hits (leakage between the six recordings).
- **fused** — the best of both: adtof decides *when and what* was hit,
  and the six per-drum recordings are used only to tell ride from crash
  and to judge how hard each hit was.

## What is the sonification?

`sonification.wav` is the original recording (at half volume) with a short
synthetic **blip added at every hit the computer transcribed**: a low thump
for kick, a noisy mid snap for snare, high ticks for hi-hat and cymbals.
Listening to it is the fastest way to check the transcription: a missing
blip = missed hit, a blip with no drum under it = false detection, the wrong
blip sound = wrong drum. No musical training needed.

## The web app

```bash
uv run drum-transcribe serve
```

Open `http://<the machine's address>:8765/` from any of your machines.

**Main page**: your projects, plus a form to transcribe a new piece — upload
a sound or video file, or paste a public link (YouTube, a Google Drive share
link, or a direct URL). Submitting creates the project page and starts all
pipelines in the background; reload the project page to watch results appear.

**Project page**: one piece, with every uploaded/linked version of it (say,
the backing track and the album recording) in its own tab. Adding another
version for comparison happens at the bottom of the page. Per version:

- players for the **original**, the **drums stem**, and each pipeline's
  **sonification**;
- while any player plays, the **bar being heard is highlighted in red** in
  the scores;
- **download links**: MusicXML (opens directly in MuseScore), MIDI, the raw
  detection data (JSON), and a ready MuseScore file when conversion succeeded
  — MuseScore 4's command-line converter sometimes refuses files its own
  editor opens fine, so the .mscz link can be missing;
- both pipelines' **scores rendered on the page** in tabs;
- a **progress checklist** and **pipeline log** link while processing runs
  (or if it fails);
- **feedback on the notation**: point at any note or rest (it turns blue),
  click to record what is wrong (extra note, missing note, wrong rhythm,
  wrong drum, wrong time signature, or free text). Flagged notes are tinted
  orange with the feedback shown on hover; click again to edit or remove.
  Clicking the score title takes general feedback. Everything is saved in
  the variant's `feedback.json`;
- a **"?" help button** on every page opens illustrated instructions.

## Running a transcription from the command line

```bash
uv sync                                          # once, installs everything
uv run drum-transcribe run song.mp3              # adtof variant (default)
uv run drum-transcribe run song.mp3 --variant mdx23c
uv run drum-transcribe run song.mp3 --variant fused
```

Results land in `output/<project>/<version>/<variant>/`; the source
recording, beat grid and drums stem are shared per version. Everything runs
on a normal CPU; a 3-minute song takes a few minutes with adtof, while
mdx23c is much slower (roughly 10× the song length).

## Honest limitations

Even the best available models mishear some things: toms are the weakest
category, hi-hat vs. ride gets confused, and flams, chokes, and open/closed
hi-hat are not detected at all. Every score needs a human check — that is
what the review website and the sonification are for. Details and the full
tool survey: `docs/adt-landscape.md`.

The ADTOF model weights are licensed for non-commercial use.

Developer/agent documentation starts at `AGENTS.md`; deeper topics live
under `docs/`.
