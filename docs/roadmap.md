# Status and next steps

## Where things stand (2026-09-20)

One project transcribed: **dancing-through-life** ("Dancing Through Life"
from Wicked) with two versions — `taustanauha` (3:12 vocals-removed backing
track for a Finnish production, click-tracked, Google Drive) and `obc`
(7:38 Original Broadway Cast recording, YouTube). Both × both variants:

| version | adtof hits | mdx23c hits | fused hits | notes |
|---|---|---|---|---|
| taustanauha | 834 | 1682 | 834 | all hits within 35 ms of grid |
| obc | 1363 | 2640 | 1363 | 5 hits > 35 ms; live pit, still tight |

The **fused** variant (added 2026-09-20, drum2midi's recipe) keeps adtof's
onsets and uses the MDX23C stems only for ride/crash disambiguation and
per-drum velocities; on taustanauha it split adtof's 40 "cymbal" hits into
27 ride + 13 crash.

The web app (projects, uploads/URLs, background jobs, progress, tabs,
sonifications, score feedback, help) is feature-complete for review work.

## Known issues

- **mdx23c over-detects** (~2× adtof): stem bleed + a generic librosa onset
  detector. Untuned; the cymbal-dominance rule is the only filter so far.
- **.mscz conversion fails** for 4 of 6 scores (MuseScore CLI importer
  quirk; MusicXML itself opens fine in the MuseScore GUI).
- ADT model limits (inherent): no open/closed hi-hat, flams, chokes; toms
  weakest class; adtof can't tell ride from crash.
- Feedback keys break if a score is regenerated with different notation.
- Port 8765 may need opening in the laptop's firewall (see
  [operations.md](operations.md)).

## Agreed / floated next steps

- **Feedback-driven correction** (needs refinement before starting): use
  collected `feedback.json` to auto-correct scores and/or tune pipeline
  parameters. Two possible directions, scope still undecided:
  - regenerate MusicXML with the human fixes applied (per-note correction);
  - use the corrections as ground truth to tune detector thresholds per
    song (systematic improvement).
  Open questions: how feedback annotations map back to specific hits
  (feedback keys currently break on regeneration — see Known issues), and
  which direction gives the most value for the least complexity.
- **Play-from-bar inside MuseScore** ("Route 2", agreed 2026-09-20): a tiny
  QML plugin for MuseScore Studio 4.7 (user runs 4.7.4.1 on NixOS) reads the
  selected bar and POSTs it to this server; the server pushes a seek event
  to the open project page, which plays the recording from that bar (web-app
  click-to-play shipped 2026-09-20 provides the seek mechanism). Prior art
  to borrow from: hoshi005/musescore-audio-sync (GPL-3, MS 4.6+). Known MS4
  limits: no dock panels / selection-change events (UX = select bar + press
  plugin shortcut), plugin can't play audio itself.
- Make the port 8765 firewall opening permanent (the user does this).
- Possible GPU rental for batch/faster MDX23C (pre-approved by user).
- PDF export (Verovio can render server-side) if printed parts are wanted.
