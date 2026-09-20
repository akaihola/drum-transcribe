# Notation rules and the MuseScore importer

MuseScore 4's MusicXML **CLI importer aborts silently (exit 40, no output,
no message)** on constructs its own GUI merely warns about. A whole
debugging afternoon distilled into rules — `score.py` enforces all of them;
break one and .mscz conversion dies again with zero diagnostics.

## Rules score.py must keep

1. **Only conventional durations.** Arbitrary gap fractions (5/6, 7/24…)
   make music21 emit tuplets like 6:5, 12:7, 24:17 — fatal. Notes and rests
   snap down to `STRAIGHT_QL`/`TRIPLET_QL` values.
2. **Stay on the beat's own grid.** Quantization picks one subdivision per
   beat; notation must use that family and never cross a beat boundary
   (`_fit_ql` caps at the boundary). Mixing grids inside a beat produces
   1/24-beat fragments and 128th-note tuplet rests — fatal.
3. **Fill rests explicitly** (`_rest_steps`). music21's `makeRests` fills a
   17/6-beat gap with ONE rest in a 24:17 tuplet — fatal.
4. **Merge near-coincident hits** (< 1/12 beat apart, adjacent straight vs.
   triplet slots) into one chord; dedupe same instrument keeping the louder.
5. **Run `makeNotation` at export** — MuseScore cannot infer tuplet brackets
   from time-modification alone on mixed triplet runs (a lone note at 23/6
   was enough to kill the import). makeNotation is safe *only because* of
   rules 1–3; fed unconventional durations it invents the fatal fragments
   itself.

## Debugging technique that worked

Schema validation passes and Verovio renders even fatal files — useless
signals. What worked: bisect by exporting measure ranges with
`music21 .measures(lo, hi)` and converting each; judge success by **output
file existence, not exit code**; then dump the failing bar's notes
(duration/type/time-modification) with ElementTree and compare against the
source events.

## Environment traps

- **Never convert via NixOS `, mscore`**: two nixpkgs packages provide
  `mscore` (mainline `musescore` and the `musescore-evolution` fork) and
  comma picks unpredictably — this produced hours of contradictory
  "nondeterministic" results. Pin `nix run nixpkgs#musescore --`
  (what `export.py` does). `QT_QPA_PLATFORM=offscreen` required headless.
- Conversion still fails on some valid files (importer quirk; its GUI opens
  them fine via an "Ignore" button the CLI lacks). Hence: **MusicXML is the
  primary deliverable**, .mscz best-effort; the web UI hides missing .mscz
  links. Status per file: only taustanauha/adtof converts today.
