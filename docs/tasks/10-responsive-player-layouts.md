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
