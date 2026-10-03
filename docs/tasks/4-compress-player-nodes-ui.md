# Compress player nodes UI

Now that waveforms are shown in the separate player and not in the player nodes,
we could use UI space more economically in the nodes. Make three proposals for
how the arrow-connected nodes could take less space but still remain equally
usable both on desktop and on portrait mobile.

## Plan, 2026-10-03

Provide three interactive proposals at `/player-layouts` on the existing web
server. Keep the six tracks and their real connections visible or reachable,
with one shared player and a details area for explanations and downloads.
Use recordings already on the server so selecting tracks and opening files can
be tried. The project pages keep their current layout while these are compared.

1. **Compact tree.** Keep the familiar four rows. Make the whole node a large
   selection button; move help, counts and downloads to the shared details area.
2. **Sideways flow.** Use four columns on desktop. On phones, use full-width rows
   with arrows in the left margin. Keep all six tracks directly selectable.
3. **Fold-away sources.** Keep the three transcription tracks visible. Put the
   original, drums and without-drums tracks behind one disclosure. Retain arrows
   from its drums-stem summary to the transcription tracks while folded.

Use the existing paper, ink and teal colors. Keep touch controls at least 44 px
high, keyboard focus visible and selection named in text. Include a portrait
preview on desktop and let the page fit a real phone without horizontal scrolling.
Show sample processing and failed states separately from real recording status.

Verify all proposals with PinchTab, including narrow screens, selection,
disclosure, help, downloads and sample progress. Review the code and run the
cached pipeline smoke check before merging. Record findings here and mark the
proposal task complete awaiting user acceptance. Implementing a chosen design
is a later task.

## Proposals and verification, 2026-10-03

The interactive comparison is at `/player-layouts`. Each proposal uses the same
recording selector, audio player, track descriptions, hit counts and downloads.
Selecting a track pauses playback and preserves its position; changing layouts
or opening the source branch preserves playback. Sample processing and failure
states let the unavailable tracks be inspected without starting a job.

Recommended proposal: **compact tree**. It keeps all six tracks one tap away
and retains the existing fork-and-merge layout. Fold-away sources needs an extra
tap to return to source tracks, so it trades convenience for space.

Measured diagram heights with ready tracks in Chromium:

| Proposal | Desktop, 1280 px screen | Phone, 390 px screen |
| --- | ---: | ---: |
| Compact tree | 314 px | 308 px |
| Sideways flow | 140 px | 366 px |
| Fold-away sources, closed | 216 px | 212 px |

The existing phone pad diagram measured 542 px at 390 px screen width. The
compact tree is about 43% shorter. These measurements cover the diagram only;
the shared player and selected-track details sit below it.

Validation:

- PinchTab checked 320, 360, 390, 430 and 1280 px viewports. All three layouts
  fit without horizontal page scrolling. Visible buttons, selectors and download
  links measured at least 44 px in both dimensions. The closed source summary
  wraps at 320 px, making that diagram 237 px tall.
- Checked the six arrows, collapsed and expanded sources, track selection,
  Tab focus, sample progress at 42%, failure text, hit counts and download URLs.
  Unavailable tracks remain selectable for their details, with no audio loaded.
  Browser playback advanced; opening sources kept it playing, and selecting a
  different track paused it while retaining the position.
- Inspected phone tree and rail screenshots and the desktop sideways flow.
  PinchTab screenshots outside the viewport intermittently timed out; bringing
  its tab forward and scrolling to the diagram allowed visual inspection.
- JavaScript syntax, Python compilation and `git diff --check` passed. `ty`
  reports the same two pre-existing optional `etag` argument errors in
  `serve.py` on both main and the feature branch.
- Cached ADTOF smoke run used a temporary copy of the taustanauha recording
  and caches. It produced 393 beats, 834 events, MIDI, MusicXML and Opus, with
  one event over 35 ms quantization error. MuseScore export succeeded after
  clearing `LD_LIBRARY_PATH` for that subprocess; the inherited Nix libraries
  otherwise conflict with MuseScore's glibc. Original results were unchanged.

The preview is served on the laptop's existing port 8765. It has not been
deployed to the cloud. The chosen layout still needs a separate implementation
task; this issue requests the three proposals only.
