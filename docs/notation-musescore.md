# Notation rules and the MuseScore importer

MuseScore 4's CLI converter exits with code 40 and no output on stdout or
stderr when the imported score fails its corruption check (the GUI shows
the same check as an "open anyway?" dialog). 40 is `InFileFailedLoad` (1320)
truncated to 8 bits. **The real reason goes to MuseScore's log file**:
`~/.local/share/MuseScore/MuseScore4/logs/MuseScore_<date>.log`, line
`failed load notation, err: [2009] Incomplete measure: … measure 66 …
Found: 49/48. Expected: 4/4.` `score.py` follows the rules below; break one
and conversion fails again.

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
6. **Every triplet length counts in eighth-note triplets** (`_duration`:
   3:2, normal-type eighth, one beat). music21's default gives 2/3 a
   quarter-triplet and 1/6 a 16th-triplet; a beat mixing them completes
   neither tuplet, so no `<tuplet>` brackets get written and MuseScore
   groups the notes wrong -> overfull bar (49/48, 100/96, 98/96). This
   fixed 10 of the 11 failing scores.

## Debugging technique that worked

Read the MuseScore log first (see top). Schema validation passes and
Verovio renders even fatal files, so neither tells you anything. Before the
log was known, what worked: bisect by exporting measure ranges with
`music21 .measures(lo, hi)` and converting each; judge success by **output
file existence, not exit code**; then dump the failing bar's notes
(duration/type/time-modification) with ElementTree and compare against the
source events.

## Environment traps

- **Never convert via NixOS `, mscore`**: two nixpkgs packages provide
  `mscore` (mainline `musescore` and the `musescore-evolution` fork) and
  comma picks unpredictably — this produced hours of contradictory
  "nondeterministic" results. `, musescore` is unambiguous (what
  `MUSESCORE_CMD` is set to here). `QT_QPA_PLATFORM=offscreen` required
  headless.
- `musescore -f` (`--force`) skips the corruption check and writes the
  .mscz anyway. `export.py` converts without it first; on refusal it saves
  the logged reasons to `mscz-problems.txt` next to the score, then
  converts again with `-f`. The pipeline prints the reasons; the web UI
  puts a red "!" on the MuseScore icon with the reasons in its tooltip.
- A broken beat grid still trips the check: `vast-test/beats.json`
  numbers a beat 5 in 4/4 time, which wraps onto the next downbeat and piles
  two beats of hits into one.
