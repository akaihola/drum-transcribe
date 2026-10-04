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

## Follow-up requested, 2026-10-04

The user confirmed that recording works at localhost:8765. Plain HTTP at atom
disables microphone access. Merge the selected player into the backing lane.
Clicking a grid track selects it; a separate triangle inside its right edge
selects and plays it. Apply this on phones and wider screens. For YouTube
originals, show the embedded video when listening to the backing alone, and the
waveform with decoded audio when recording or mixing the local take. Preserve
transport position, recording, downloads and help. Verify actual playback,
selection without playback, video transitions and recording in the browser.

## Follow-up implementation and verification, 2026-10-05

The user confirmed recording works at localhost; plain HTTP at atom was the
cause of the reported disabled recording controls. The follow-up merges the
selected track's help/downloads into the Backing lane and uses its shared
transport. Track labels select without starting playback; separate right-edge
triangles select and play, or pause the current track. Phone Listen now also
shows the backing/recording view. The Record tab still opens that view directly.

YouTube originals use a full embedded player for backing-only listening. The
waveform and decoded audio take over for recording or an audible local take.
Mute switches back to video; unmuting restores waveform playback. The video
clock drives the counter while the embed plays, including buffering. Embed
errors fall back to downloaded audio with a message.

Verified with the T3 browser on an isolated server at port 8768:

- Actual Highway Star YouTube playback, shared seeking to 60 seconds, pause and
  resume through the YouTube API controls, and a simulated embed error. The
  fallback kept playing decoded audio at the same position without duplicate
  sources. The embed itself loaded from YouTube, not a mock.
- Selection without playback and triangle playback on desktop and phone;
  the same selection/play distinction with native audio at insecure atom HTTP.
- Capture through the real AudioWorklet using a generated 440 Hz MediaStream
  in place of the microphone. Recorded about 6.7 seconds, verified nonzero
  captured samples, and replayed them with both local and backing sources.
  Recording switched video to waveform; Mute and unmute switched both ways
  while preserving position. This checks capture and transport integration,
  not physical microphone permissions or measured acoustic alignment.
  The generated take was cleared from the test origin afterwards. Production
  browser recordings and saved project files were not modified.
- Phone layouts at 320, 390, 640, 768, 834 and 1024px, using same-origin frames.
  No horizontal overflow. Selection buttons were at least 51px wide in these
  checks; play and help targets are 44px. The diagram switches from tree to
  sideways as space grows. Listen shows the shared transport and lanes.
- JavaScript modules and interpreted inline scripts passed syntax checks;
  Python compilation and whitespace checks passed. Type checking reports only
  the two previously documented optional-etag errors in serve.py.
- Cached ADTOF pipeline smoke run in a temporary directory produced 393 beats,
  834 events, MIDI, MusicXML, MuseScore and Opus audio. One event exceeded
  35 ms quantization error, as in the previous check.

Laptop deployment only, at http://localhost:8765/p/highway-star. Task [10]
remains pending user acceptance.

## Cropping correction requested, 2026-10-05

Restore the cropped YouTube timeline/control strip in the Backing lane. On a
new backing selection, immediately hide the previous video or waveform while
the replacement loads. Show loading status in its place and reveal the new
player only once ready. Verify both video-to-waveform and waveform-to-waveform
changes with a held download, including failure recovery.

The correction crops the bottom 3.5rem of a 200px iframe, retaining the
timeline/control strip while hiding the video and title. The shared backing area shows loading text instead of either
player whenever a backing request is pending. Success reveals the replacement;
failure or cancellation restores the still-selected backing.

Verified in the T3 browser on port 8768: actual Highway Star YouTube playback
inside the 56px strip, a held video-to-waveform download, a held
waveform-to-waveform download, and a simulated HTTP 503 with recovery of the
previous waveform and its error message. JavaScript syntax and whitespace
checks passed. This correction changes only presentation; the pipeline and
capture code are unchanged.

## Layout refinements requested, 2026-10-05

Simplify the phone Listen tab by hiding recording buttons, the routine Hearing
status, Backing title/selector and the whole local-take lane. Remove routine
saved/restored notices everywhere but retain storage failures. Add desktop
track info buttons and put the selected track's info/download icons alongside
the Backing title. Align record/mute/solo buttons, playback/microphone sliders
and dB readings; use recording red for the mic slider. Fill the backing lane
with its waveform. Tuck the desktop grid hint beneath Original, aligned with
the lower row's status, without a separate gap before the recording view.
Use a bent-left-arrow Undo icon and red on Delete this version. Put Versions
beside its buttons, and center the desktop title in the top navigation row.
Check narrow and wide layouts, info/downloads and recording/playback controls.

Implemented the requested changes. Listen mode means the existing phone Listen
tab; desktop keeps its recording controls. The selected desktop backing now
has one row of info/download actions, and each desktop node has an independent
info button. These open help without changing selection. Routine save/restore
notifications are removed; storage failures remain visible.

Browser checks used an isolated server at port 8768:

- Listen hides Record buttons, routine Hearing text, Backing title/selector
  and both the Your drums controls and waveform. Record shows them again.
  Checked 320, 390, 640, 768 and 1024px with no horizontal overflow.
- Desktop at 768, 834, 1024 and 1280px: playback/mic sliders have equal right
  edges and usable widths; corresponding dB outputs share their right edge.
  Record/mute/solo buttons have identical top/bottom coordinates. Mic and
  Delete this version use the recording red.
- The backing waveform's rendered height matches its lane. Six download icons
  plus info fit on one row beside Backing, including at tablet widths. An extra
  icon was temporarily cloned in the test DOM to check the six-file case.
- Desktop node info and Backing info show the explanation and complete hit
  counts without selecting or playing another track. A download retained its
  accessible filename/tooltip and returned HTTP 206 for a byte-range request.
- Desktop title is centered in the top navigation row; Versions is the first
  item in the version-button row. The sideways hint aligns with the lower-row
  status text, and the recording area follows the grid without an extra gap.
- JavaScript syntax and whitespace checks passed. Capture/pipeline algorithms
  are unchanged, so the earlier pipeline and AudioWorklet checks were not
  repeated. Browser screenshot capture failed at the preview client; these
  checks used live DOM, computed styles, element measurements and interactions.

Deployment is to the laptop service. User acceptance remains pending.
