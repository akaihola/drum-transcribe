# Status and next steps

## Where things stand (2026-09-20)

One project transcribed: **dancing-through-life** ("Dancing Through Life"
from Wicked) with two versions — `taustanauha` (3:12 vocals-removed backing
track for a Finnish production, click-tracked, Google Drive) and `obc`
(7:38 Original Broadway Cast recording, YouTube). Both × both variants:

| version | adtof hits | mdx23c hits | fused hits | notes |
|---|---|---|---|---|
| taustanauha | 834 | 1682 | 834 | 1 adtof hit > 35 ms of grid |
| obc | 1363 | 2640 | 1363 | 3 adtof hits > 35 ms; live pit, still tight |

The **fused** variant (added 2026-09-20, drum2midi's recipe) keeps adtof's
onsets and uses the MDX23C stems only for ride/crash disambiguation and
per-drum velocities; on taustanauha it split adtof's 40 "cymbal" hits into
27 ride + 13 crash.

The web app (projects, uploads/URLs, background jobs, progress, tabs,
sonifications, score feedback, help) is feature-complete for review work.
Play-from-bar inside MuseScore shipped 2026-09-20
([musescore-plugin.md](musescore-plugin.md)); awaiting first real use.
Its in-MuseScore settings window (server address; opens when run with
nothing selected or when the server doesn't answer) shipped later the same
day, tested end-to-end in the headless GUI.

**Barline repair shipped 2026-09-20**: beat_this doubled the tempo /
sprayed downbeats in taustanauha 2:04–2:30, chopping the score into
half-second bars (72–91). `beats.regularize()` now repairs this by default
(see [architecture.md](architecture.md) stage 2); a checkbox on the project
page keeps raw barlines for genuinely irregular pieces. Both versions were
regenerated — bar numbers shifted (taustanauha 113 → 98 bars).

## Known issues

- **mdx23c over-detects** (~2× adtof): stem bleed + a generic librosa onset
  detector. Untuned; the cymbal-dominance rule is the only filter so far.
- **.mscz conversion** works for new runs; it still fails when the beat
  grid is broken (see [notation-musescore.md](notation-musescore.md)).
  Scores made before 2026-09-25 keep their old, often failing notation;
  regenerating them would break feedback keys.
- ADT model limits (inherent): no open/closed hi-hat, flams, chokes; toms
  weakest class; adtof can't tell ride from crash.
- Feedback keys break if a score is regenerated with different notation.
- Port 8765 may need opening in the laptop's firewall (see
  [operations.md](operations.md)).

## Agreed / floated next steps

- **"Starting up…" page for the cloud copy** (live since 2026-09-25): a
  Cloudflare Worker in front of plokkaus.vempai.men shows a loading page
  while the sleeping container wakes up. See
  [loading-page-plan.md](loading-page-plan.md).
- **Feedback-driven correction** (needs refinement before starting): use
  collected `feedback.json` to auto-correct scores and/or tune pipeline
  parameters. Two possible directions, scope still undecided:
  - regenerate MusicXML with the human fixes applied (per-note correction);
  - use the corrections as ground truth to tune detector thresholds per
    song (systematic improvement).
  Open questions: how feedback annotations map back to specific hits
  (feedback keys currently break on regeneration — see Known issues), and
  which direction gives the most value for the least complexity.
- Make the port 8765 firewall opening permanent (the user does this).
- Possible GPU rental for batch/faster MDX23C (pre-approved by user).
- PDF export (Verovio can render server-side) if printed parts are wanted.
