---
depends_on: [4]
---
# Responsive player layouts

The user selected compact tree for portrait phones and sideways flow wherever
there is enough width, including desktop and suitable tablet sizes.

Implement the chosen layouts on project pages, based on available diagram width.
Keep all six tracks, their real connections, status, help and downloads usable.
Keep existing playback and recording behavior, including loading progress.
Use compact nodes and show desktop help and downloads for the selected track
below the graph. Mobile keeps its Files tab and track help.

Verify narrow screens, tablet widths and desktop, resizing without reloading,
track selection/playback, help, downloads, progress and live refresh. Run the
cached pipeline smoke check. Deploy to the existing laptop service.

## Implementation and verification, 2026-10-04

Project pages now use the chosen layouts. The switch is a container query at
44rem, so it follows the diagram's room rather than a device label. The desktop
diagram was sideways at 834, 1024 and 1280px window widths; at 820px and below it
used the compact tree. Phone pages also switch when rotated or widened.

Desktop nodes choose the existing backing controls and show one track's help,
hit counts and downloads below. A shared arrow renderer connects all six tracks
on both interfaces. Phone help buttons remain separate from playback buttons,
and their dialogs show the full hit counts. Hidden mobile media controls are
inert so keyboard navigation cannot land on them.

Checks performed with the T3 collaborative browser:

- Desktop layout at 320, 390, 640, 768, 800, 820, 834, 1024 and 1280px widths;
  phone layout at 320, 360, 390, 704, 768, 834 and 1024px. No horizontal page
  overflow. Width tests used same-origin frames after the preview resize tool
  repeatedly timed out. These are browser viewport checks, not physical-device
  or Safari tests.
- Desktop diagrams measured 308px high in tree form and 136px sideways. Phone
  diagrams measured about 340px in tree form and 152px sideways, including
  separate help buttons. All phone node actions were at least 44px in each
  dimension. Desktop help and download targets also measured 44px.
- All six arrows remain present. Help, complete hit counts, backing loading
  status and file downloads work. A download returned HTTP 206 and the requested
  byte range. Phone playback continued at the same position while resizing from
  tree to sideways. Files remained accessible in the phone's Files tab.
- Forced a live ADTOF piece refresh in the browser. The card was replaced,
  selection remained intact and exactly one details card stayed visible.
  Simulated 42% processing on an unavailable MDX23C track; its node showed the
  activity and opened the existing progress bar without starting any job.
- Checked the insecure HTTP fallback at `http://atom:8768`: native audio played
  from the node and its player appeared below the diagram. Keyboard Enter
  selected and played another node.
- JavaScript syntax, Python compilation and whitespace checks passed. `ty`
  still reports the two existing optional `etag` argument errors in `serve.py`.
- The cached ADTOF smoke run in a temporary directory produced 393 beats,
  834 events, MIDI, MusicXML, MuseScore and Opus audio. One event exceeded 35ms
  quantization error. MuseScore ran with its conflicting inherited
  `LD_LIBRARY_PATH` removed. Saved project results were not modified.

Deployment target is the laptop service on port 8765. Cloud deployment is not
part of this change. Task [4] is accepted by the user's choice; this
implementation awaits separate acceptance.

[4]: 4-compress-player-nodes-ui.md
