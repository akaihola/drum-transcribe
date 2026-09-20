# Pipeline architecture and design decisions

Goal: **note-exact forensic transcription** — preserve what was played, no
musical simplification; every intermediate inspectable and re-runnable.

## Stages

1. **Demucs htdemucs** two-stem split → drums stem (shared per version).
2. **beat_this** → `beats.json`: beat times + position-in-bar. Bar numbers =
   cumulative downbeat count; beats before the first downbeat form pickup
   bar 0. `BeatGrid.meter` = modal downbeat spacing.
3. Hit detection, two variants kept side by side, never merged:
   - **adtof**: ADTOF-pytorch 5 classes (kick/snare/tom/hihat/cymbal) at
     100 fps with per-class thresholds; velocities estimated afterwards from
     band-limited drums-stem energy (bands in `transcribe.BANDS`) so ghost
     notes survive. Conservative, the baseline.
   - **mdx23c**: MDX23C DrumSep splits the drums stem into 6 per-drum stems
     (~10× real time on CPU); librosa onset detection per stem on the
     normalized envelope (delta 0.05). Distinguishes ride/crash but
     over-detects; cymbal-family hits only count for the loudest of
     hihat/ride/crash at that frame (stems bleed).
4. **Quantize** (`quantize.py`): each beat independently picks the
   subdivision (2/4/3/6/8 slots) minimizing total onset error, so straight
   and triplet feels coexist. `Event` keeps bar, beat offset as an exact
   `Fraction`, velocity, model confidence, quantization error in ms, and the
   grid time in seconds (for audition/sonification).
5. **Render**: MusicXML via music21 (constraints in
   [notation-musescore.md](notation-musescore.md)), GM drum MIDI, and the
   sonification WAV (original at half volume + synthetic blip per hit —
   the primary by-ear QA tool).

## Why this shape

- Chosen from the 2026 survey in [adt-landscape.md](adt-landscape.md):
  drum2midi's recipe but as our own thin glue (drum2midi itself is a pile of
  research scripts; DrumLab too immature). ADTOF weights are CC BY-NC.
- CPU-only on purpose: 16-core laptop handles single songs; the user has
  offered rented GPUs if batch work ever needs it.
- Every stage writes JSON so a human (or later model) can audit any hit:
  confidence < 0.5 or |error_ms| > 30 is flagged "suspect" in the UI.
- Ground truth observed: click-tracked sources quantize with ~0 error;
  the live Broadway recording still stayed within 35 ms on all but 5 hits.
