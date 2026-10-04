# Web app internals (serve.py + ingest.py)

Stdlib-only `ThreadingHTTPServer`; HTML/JS lives in template strings inside
`serve.py`. Server state stays in the `output/` tree — every page render rescans
the filesystem (plus, for live progress, `ingest.RUNNING`: the version
dirs whose job thread is alive in this process). All
responses carry `Cache-Control: no-cache` (re-runs replace files in place;
without it browsers heuristically cache and render stale scores), and
`/files/**` supports byte ranges (Chromium won't seek audio otherwise).

Browser-local drum recordings use IndexedDB and never enter server storage.
Their transport, capture and export code is in explicitly served JavaScript
modules under `src/drum_transcribe/static/`. See the local recording section
below and [implementation results](local-recording-handoff.md#implementation-results).

## Routes

| route | what |
|---|---|
| `GET /` | main page: project list + create form |
| `GET /player-layouts` | three interactive compact-node proposals, with existing recordings and a portrait preview; project layouts are unchanged |
| `GET /p/<project>[/<version>]` | project page: version tabs, players, scores, feedback; opens `<version>`'s tab (else the first), and switching tabs rewrites the address (`history.replaceState`) |
| `GET /api/index` | JSON of projects → versions → variants (from `scan_output`) |
| `POST /api/create` | `{project, version, url, gpu?}` → slugify, start a background job (with `gpu` in the cloud: save the job record first, 503 if that fails); answers the slugs `{project, version}` so the form can open the new tab |
| `PUT /api/upload?project&version&filename&gpu=1?` | raw file body (no multipart) → job; a body shorter than its Content-Length is refused (400); with `gpu` in the cloud the original is stored in the bucket before the job is accepted; same answer |
| `POST /api/unlock` | `{password}` → scrypt check → bypass cookie (see Throttling) |
| `POST /api/feedback` | set/delete one feedback entry, returns variant's map (gated) |
| `POST /api/rawbars` | `{project, version, raw}` → flip `keep-raw-bars` flag, re-run here, or for a cloud GPU version start a new generation on a GPU; refused while the version has work or an unsettled rental, and for cloud versions made before job records (gated) |
| `POST /api/delete` | `{project, version}` → remove the version dir, and in the cloud its bucket objects, inputs and job record (`gate.forget`, else the next cold start re-syncs them); refused while it has work or an unsettled rental (gated) |
| `POST /api/retry` | `{project, version}` → a failed cloud GPU job starts over (new generation, five more rentals) once its rentals are settled (gated) |
| `POST /api/seek` | `{bar}` from the MuseScore plugin → bump seq; same bar twice flips `playing` |
| `GET /api/seek` | current `{seq, bar, playing}`; pages poll it every 1 s |
| `GET /api/progress?project=` | per version: `progress.version_progress` (see Live progress); polled every 2 s while a job runs |
| `GET /static/<asset>` | explicit image and recording-module allowlist, with their content types |
| `GET /files/**` | static from the output root |

`scan_output` reports `drumless`, the URL of
`stems/htdemucs/*/no_drums.ogg` (Opus; older results have only
`no_drums.flac`, used instead — `progress.playback_stem`), alongside
`source` and `drums`. A separate "without drums" card beside the drums stem
in the flow diagram plays this track and offers a download named
`<project>-<version>-without-drums.<ext>`.
It uses the same shared volume, score following and play-from-bar controls
as the other audio.
Its progress follows the Demucs step; its file also changes the progress
signature so it appears during a running job without reloading the page.

`scan_output` also derives per-version: `error` (log tail contains
"ERROR:"), `tracked` (beats.json exists), `progress` (same as
`/api/progress`), and `irregular`/`raw_bars` — whether `regularize()`
would change the raw beat grid (then the meter switch above the score is
enabled) and whether the `keep-raw-bars` flag file is set. Switching the
meter option POSTs `/api/rawbars`, which starts `start_rerun_job`: re-runs
the pipeline for each variant that has `onsets.json`; cached stages make
this take seconds, but note it renumbers bars, which orphans feedback keys.

## Throttling (gate.py)

Creation (`/api/create`, `/api/upload`) is throttled, and editing existing
results (`/api/feedback`, `/api/rawbars`, `/api/delete`) need the unlock cookie outright,
only where the `CREATE_PASSWORDS` env var is set — in practice the cloud
container; the laptop server stays unlimited. Design notes (all forced by
the serverless platform: scale-to-zero kills memory, instances don't share
it):

- **Global cap, no per-IP state**: at most `THROTTLE_MAX` (3) anonymous
  creations per `THROTTLE_HOURS` (24), counted from `created` marker files
  in the version dirs. The timestamp is in the file *content* — mtimes lie
  after every bucket re-sync. Markers are best-effort uploaded to the
  bucket at creation so cold starts still see them, and so are
  `source-url.txt`, `feedback.json` and the `keep-raw-bars` flag (removing
  the flag deletes its copy). `gate.keep` mirrors them through one queue,
  so the newest save lands last. `auth` markers (created
  with a valid cookie) don't consume the anonymous budget.
- **Unlock**: past the cap the create form reveals a password field;
  `/api/unlock` checks scrypt entries (`salt:hex` comma-separated in
  `CREATE_PASSWORDS`, one per person — `drum-transcribe hash-password`
  makes them) and answers with a `create_token` cookie
  (HttpOnly/Secure/SameSite=Lax, 1 year).
- **Edits need the cookie, not the budget** (`_may_edit`): feedback text
  lands in someone else's results and a meter switch costs a re-run, so
  anonymous visitors get 403 — the anonymous creation budget buys creation
  only. The page answers a 403 by prompting for the password and retrying
  (`postGated`), so a password holder can unlock from the score too, not
  just from the create form.
- **Token**: stateless — `HMAC(TOKEN_SECRET, salt of the matched entry)`.
  Deleting a person's entry revokes their tokens; rotating `TOKEN_SECRET`
  revokes all. Brute force is answered with passphrase entropy (~72 bits)
  plus a 1 s delay on failure, not with lockout counters (which would be a
  DoS button and need durable state anyway).

## Fetching a new version (ingest.py)

Daemon thread per new version: fetch (yt-dlp for YouTube, gdown fuzzy for
Drive share links, urllib otherwise; ffmpeg -vn extracts audio from video or
unknown containers) → run `python -m drum_transcribe.cli run` per variant
(adtof first for fast feedback), everything appended to
`<version>/pipeline.log`. Failures land in the log as `ERROR: …`. A link-created
version also keeps its link in `source-url.txt` (uploaded to the bucket in
the cloud, like `created`); `scan_output` reports a YouTube video id from it
as `youtube`.

`ingest.check_url` decides which links the fetchers may open at all —
everything fetched is served back from `/files/…`, so a link is a read
primitive:

- **Scheme**, everywhere: `http`/`https` only. urllib, yt-dlp and gdown all
  open `file://` (and `ftp://`) happily, and `file:///proc/self/environ`
  would hand a visitor every secret env var at once.
- **Address**, only where the throttle is on (the cloud container): the host
  name is resolved and every address it answers with must be globally
  routable — no `localhost`, `10.x`, `169.254.169.254`, or neighbour in the
  datacentre network. The laptop skips this half; fetching from the home LAN
  or the tailnet is normal there.
- **Redirects**: the urlopen opener re-checks every hop (`_CheckedRedirect`),
  because a public link may bounce inwards. urllib's own redirect handler
  refuses `file://` hops before ours even runs.

`POST /api/create` calls it before creating anything, so a bad link is a 400
with no project directory and no throttle marker spent. Not covered: DNS
rebinding (the name is resolved once for the check, again by the fetcher),
and hops yt-dlp or gdown follow on their own — both need a public host to
start from.

The new-version form's "process on a rented cloud GPU" checkbox appears
only in the cloud web app (`jobs.enabled()`: the job-record key and the
Vast key are set), ticked by default. Such a job is not a thread:

- The request saves a record in the `drum-transcribe-jobs` bucket
  (`jobs.py`, conditional writes) and wakes the coordinator; an upload's
  original goes to `sources/<job>/upload.<ext>` first.
- The coordinator (`coordinator.py`, one thread, at startup and once a
  minute) fetches the recording beside the rental (`ingest.prepare`:
  the same fetchers, each within 15 min) and publishes it as
  `sources/<job>/source.<ext>`; rents a Vast instance whose onstart runs
  the worker baked into the GPU image; and copies each variant into
  `output/` once its `done` marker names the record's generation. A
  failed rental is replaced, up to five per generation; then the page
  offers "Try again".
- Its stage lines go to the local `pipeline.log`, which the coordinator
  also saves as `<song>/<version>.log` in the job bucket and restores
  after a cold start. The worker's own log arrives as
  `workers/<claim>.log` beside the results.

On the laptop the checkbox is gone: only the cloud web app rents. Submit
through the cloud form and pull results with `rclone sync`
([gpu-workers.md](gpu-workers.md) §3).

## Front-end notes

- Visual tokens and component rules: [style-guide.md](style-guide.md);
  the living specimen is served at `/style`. Teal = "sound happens here"
  (now-playing bar, active tab, primary button); brass = in progress /
  saved feedback; red = suspect hits and errors.

- Scores rendered client-side by Verovio (CDN, WASM). Race trap: resolve a
  ready-promise from `verovio.module.calledRun` OR `onRuntimeInitialized`.
- `svgAdditionalAttribute: ["measure@n"]` tags each SVG measure with its
  bar number → used by both playback-follow and feedback addressing.
- Playback follow: `timeupdate` (capture phase) on any `<audio>` inside a
  `section[data-song]`; bar times computed from `beats.json` (bar counter
  increments on `positions[i]==1`). Highlight only — auto-scroll was removed
  on user request.
- Score interaction: playback is the default. Touch/left-click anywhere in
  a bar, including notes/rests, seeks the version's audio to that bar and
  plays. The `Comment on symbols` button toggles `commentMode`, reflected
  by `aria-pressed` and the body's `comment-mode` class. It applies across
  every version/variant for this page visit and survives live score refresh;
  reloading resets to playback. In comment mode, touch/left-click opens
  feedback for the symbol or, on empty staff space, the whole bar, without
  seeking or starting audio. Right-click reverses the action without
  changing the mode. A `contextmenu` handler suppresses the native menu
  inside scores and checks the pointer type, falling back to the last
  `pointerdown` for older browsers, so touch long-press never invokes the
  mouse override. `scoreGesture` handles both routes and keeps feedback
  menu controls out of score actions. Measures use the clicked element's
  ancestor first, then `getBoundingClientRect` hit-testing for empty SVG
  space (hidden tabs have no layout, so rects can't be precomputed).
  Playback on the score title does nothing, since it has no bar. Player choice
  (in `seekToBar`): currently playing > last played (`play` events, capture)
  > first in section. `preload="none"` means seek must wait for
  `loadedmetadata`.
- MuseScore play-from-bar: the page polls `GET /api/seek` every 1 s and on a
  new `seq` applies the server's state: `playing` false → pause all audio,
  true → `seekToBar` on the active version tab. The **server** owns the
  play/pause toggle (POSTing the same bar twice flips `playing`); pages must
  never decide from their own audio state — when two pages are open with
  different states, local decisions make them hand playback back and forth
  on every pause press (bug found 2026-09-20). Browsers block script
  playback until the user has clicked play once per page load. Stale pages
  keep the old JS until reloaded.
  See [musescore-plugin.md](musescore-plugin.md).
- Tabs are generic: any `.tabbar button[data-target]` toggles the
  `.tabpanel#id` children of its closest `.tabs`; the tabbar itself may be
  nested deeper (the score selector lives inside `.scorehead`). The version
  tabbar ends with a "+ add a version" tab whose panel adopts the
  server-rendered `#addform` node. Meter-switch buttons (`.mopt`) share the
  tabbar styling but have no `data-target`, so the tab handler skips them.
- `static/track-layout.css` uses a four-row compact tree below 44rem of available
  container width and a four-column sideways diagram above it. This applies to
  the desktop selector and phone pads, including resizing without reloading.
  `track-layout.js` draws the same six derivation arrows from the nodes' current
  positions, with a unique SVG marker per version and an accessible description.
  The original splits into without drums and drums stem; the drums stem feeds
  ADTOF and MDX23C; both feed Fused.
  On desktop the script adds a `.track-picker` and keeps the existing `.flow`
  as `.track-details`. Only the selected track's original controls, help,
  hit counts and downloads are visible. All media remain in the DOM, so the
  shared transport, score seeking and live piece replacement continue to work.
  A mutation observer reflects backing download progress and pipeline status;
  a resize observer redraws arrows. Choosing a ready track uses its existing
  backing selector, or plays its native player where recording is unavailable.
  An unavailable track opens its progress details without starting any job.
  Download tiles are at least 44px, retain their tooltips and drag-out
  `DownloadURL`, and use the existing MuseScore, MusicXML, MIDI and JSON icons.
  Players stretch to the details width;
  Chromium's per-player volume controls are hidden in favour of one shared
  `.vol` slider (remembered in `localStorage`). Players are `preload="none"`
  until their version tab is shown (`showPanel` flips them to `metadata`),
  so durations appear without fetching ~0.4 MB per file for hidden tabs. Every title has
  an `i` popover (`INFO`/`infoBtn`) explaining the artifact. Anything not
  ready has a progress bar (`progBar`) where its player will be; pipeline
  logs are in the `#gear-btn` popover.
- `[hidden]` is forced to `display: none !important`: any rule giving an
  element a `display` (e.g. `form.create label { display: block }`) beats
  the bare attribute, which kept the create form's password field on show
  for everyone until 2026-09-28.
- YouTube originals: when `v.youtube` is set and the recording has been
  downloaded (a progress bar until then), the original node holds a
  `<yt-audio video=ID>` custom element instead of `<audio>`. It wraps the
  IFrame API player behind the `<audio>` surface the page uses (`paused`,
  `currentTime`, `volume`, `play()`, `pause()`, dispatched `play` and a
  250 ms `timeupdate`), and every media lookup uses the `MEDIA` selector
  (`"audio, yt-audio"`), so seekToBar, bar follow, the shared volume and the
  plugin treat it like any player. Seeks and plays before the API is ready
  are queued. Cropping: the iframe is 4.4rem tall — YouTube's compact layout
  at that height puts the progress bar at the top and play/pause in the
  middle — shown through a 2.6rem window offset by .6rem. Before the first
  play (the "cued" state) YouTube's share/"watch on YouTube" row covers its
  own play button at every height under ~140px, so a transparent `<button>`
  over the strip calls `play()` and is removed on the first PLAYING; after
  that YouTube's own controls take clicks (verified in Chromium and Firefox,
  default autoplay policy, sound unmuted). YouTube autohides
  its controls ~3 s after the mouse leaves; no player parameter prevents
  that any more (verified 2026-09-25).
- Live refresh: the panel is built from `versionPieces(v)`, each piece's
  root carrying `data-piece`. `pollProgress` fetches `/api/progress`
  every 2 s while a job runs and the page is visible; `showProgress`
  updates the bars in place (width, caption, `data-tip` tooltip, aria).
  When a version's `sig` (job state + result-file mtimes) changes,
  `refreshVersion` re-fetches `/api/index` and swaps in only the pieces
  whose HTML changed — never one with a playing `<audio>` — after
  running their bars to 100 %. A new score keeps the selected score tab.

## Phones (max-width 40rem)

Pages carry a viewport meta (without it phones laid them out 980 px wide
and shrank everything). `renderScores` engraves for the score's real width
at `SCORE_SCALE` (default 45, `localStorage.scoreScale`), as one tall page
(`pageHeight` 60000, narrow margins: no page numbers or gaps in the
scroll), with the "Percussion"/"Perc" staff labels stripped from the XML.

The phone layout ("drum pads", chosen from three prototypes in September
2026) is `static/mobile.css` + `mobile.js`, loaded by a head script only on
narrow screens (`html.mobile`). It decorates the desktop DOM rather than
replacing it: the real players stay in the hidden `.flow`, and the pads,
header, version `<select>`, bottom tabs (Listen/Score/Files/Record) and mini
player drive them. The hidden `.flow` is inert to keep its invisible controls
out of keyboard navigation. The compact pads keep their separate 44px help
buttons; help also shows full hit counts when the short pad caption is clipped.
Live refresh replaces `[data-piece]` elements, so the
decoration is idempotent and re-runs on the `rendered` event that `build`
and `refreshVersion` dispatch. In the Record tab the transport is one line
(Undo moves into the ⋯ menu, the view switch is hidden; pinch zoom replaces
it, see below).

## Live progress (progress.py)

Every stage line in `pipeline.log` is `== what == <UTC time>`
(`ingest.marker`; `stage` in vast-worker.sh). For a cloud GPU version
the record replaces the job thread: its state gives running/failed/none,
its `done` list which variants are ready, its `status` the cloud GPU
bar's text while waiting (checking a previous rental, the daily limit,
no affordable offer), and the current worker's log is read after the
web app's own. `version_progress` takes
the current job's part of the log (after the last `all pipelines
finished`/`ERROR:`), maps each marker to a task (`src`, `gpu`, `drums`,
`adtof`, `mdx23c`, `fused`) and step via `STEPS`, and estimates:

- **Expected step time** = fixed + per-song-second, CPU or GPU column,
  measured 2026-09-22 on atom (60 s clip: Demucs 0.34×, MDX23C 6.5×
  song length, the rest seconds) and for the GPU from one timestamped
  run on an RTX 3090 (2026-09-25, 4.6 min song; see gpu-workers.md §4).
  On the GPU "writing outputs" includes the per-variant bucket upload,
  the slowest step there. The
  image-pull step is `45 s + 6 × 8 GB / host download speed`, the speed
  coming from the offer line the coordinator logs when renting
  (`host downloads at N Mbit/s`; Vast reports no pull progress at all:
  its `status_msg` stays empty and `disk_usage` is -1 while loading).
  The recording's own bar keeps its clock while the rental runs beside
  it.
- **Real progress** overrides the guess where a step prints it: yt-dlp's
  `45.3% of`, tqdm's `45%|` (Demucs on CPU; the GPU worker disables tqdm).
- Past its expected time a step creeps (asymptotically, never to 100 %)
  and says "taking longer than usual"; times left are then unknown.
- Task states: `queued` (hatched, still bar), `running`, `arriving`
  (done on the GPU, files not copied yet, at most a minute or two),
  `failed`, `stopped` (log unfinished but no job thread: the laptop
  server restarted; cloud GPU jobs carry on instead). A task with its
  file present gets no bar, also during a meter re-run (old results stay
  playable; the meter shows "recomputing…").

## Feedback

Stored per variant in `feedback.json`:
`{"<bar>:<symbol-index>": {"labels": [...], "text": "..."}, "bar:<bar>": {...}, "title": {...}}`
where symbol-index counts `g.note, g.rest` in document order within the
measure — stable across reloads for identical score files, NOT stable if a
pipeline re-run changes the notation. Empty labels+text deletes the entry.
Existing symbol and title keys remain compatible. Whole-bar comments use
`bar:<bar>` and attach to `g.measure`; they tint its barlines and bar number
orange without recoloring its notes. Saved symbol comments tint the symbol
orange. Both get an SVG `<title>` tooltip. Hovering symbols in comment mode
also turns them orange. The commenting action on `g.pgHead` opens
whole-transcription feedback. The menu stays within the viewport, including
on narrow touchscreens. Stored text is attacker-controlled input:
put it in the DOM via `textContent`/`.value` only — it was once interpolated
into the edit menu's `innerHTML`, where `</textarea><img onerror=…>` ran as
script for whoever clicked the note.

## Browser-local drum recording

`local-recording.js` adds one `Recording` per version once its source is ready,
including when live progress supplies that source. On secure pages with
AudioWorklet support, `practice-audio` replaces the native players and YouTube
iframe with a "Use as backing" button; it keeps the media-element interface
(`paused`, `currentTime`, `play()`, `volume`, events) that score highlighting,
click-a-bar and MuseScore polling use. The one transport lives in the arrange
view mounted after `.flow`: a toolbar (transport, bar.beat counter, Undo,
whole-song/follow-16-bars view, status line, ⋯ menu with export, import,
latency and Clear), a bar ruler, a Backing lane and a Your drums lane, all
canvases whose static layer is cached per view and redrawn with the playhead
every 50 ms tick. The counter uses tabular digits in fixed-width slots, so
ticking never shifts the toolbar. A mouse seeks on press and drag. Touch
seeks on a tap or a sideways drag (the lanes are `touch-action: pan-y`, so
vertical swipes scroll the page), and two fingers pinch the time axis:
`view` holds the zoomed `[t0, t1]` (null = the Whole song/Follow setting),
anchored under the fingers' midpoint. `shownRange` pages the view to the
playhead while playing or after a seek, never while the fingers pan. Takes are runs of
segments sharing a `take` id (older data: the chunk id without its frame
suffix). Saved takes are drawn from IndexedDB (`preview`) before the first
user gesture creates the AudioContext. Space, R, M, S, Home and Ctrl/Cmd+Z act
on the visible version unless focus is in a text field, select or dialog.
Insecure pages keep the original players.

Choosing a backing immediately highlights its button and updates the Backing
menu. The button's ring fills from 0 to 100% with the same download percentage
as the waveform lane and status line. It spins while the download size is
unknown or the audio is being prepared. The current audio keeps playing
until the new backing is ready. Another choice cancels the pending download;
Pause also cancels it and stops playback immediately. A failed load restores
the previous choice and offers a retry by choosing the same node again.
Only the requested choice is displayed early: the playback clock and remembered
export mix keep using the backing actually heard. Original's initial decoded
audio is reused, and choosing the already loaded backing does not download it
again or split an ongoing take. Decoded backings are not accumulated in memory.
The recording entry script has a version query in `PROJECT_HTML`; bump it when
changing that script. The cloud CDN caches its unversioned URL for four hours
despite the server's revalidation header, so a deployment alone can leave the
old player in use.

Version changes stop/disarm recording and release the decoded backing. Refreshes
rebind changed controls without replacing the track or active audio graph.
Changed progress signatures invalidate the decoded backing for the next Play,
while preserving the currently heard buffer. Undo-only chunks stay in memory
during this visit and are not retained in IndexedDB.

One 48 kHz AudioContext schedules the selected backing and nearby local chunks.
It bounds derived tails to the source length and supplies silence for short
backings. Local chunks are scheduled two seconds ahead, rather than creating
sources for a whole song at once. A WaveShaper clips the sum to [-1,1] before
the listening-only master gain. Solo silences backing during Play back; Mute
and Record still play backing. Record never plays the local track or microphone.

`recording-grid.js` turns beats.json into bars and beats, extended four bars
before the first beat at the opening tempo. Play with Record armed sets `from`
two bars before the record point (`leadStart`); `anchor` puts that song time
0.05 s ahead, capture starts exactly at the record point, and `current()` runs
from `from`, negative during a count-in. Oscillator clicks, accented on
downbeats, are scheduled for beats before 0:00 on the listening path only; a
lead-in reaching before 0:00 starts on the nearest downbeat. Pausing during
the lead-in cancels the passage and keeps the record point. Without beats.json
there is no lead-in. Seeking, song end, errors, interruptions and version
changes disarm Record to Play back; only M mutes.

`recording-worklet.js` batches 4096 captured samples with absolute audio frame
positions. An 8192-frame pre-roll buffer covers slightly late start commands.
It emits zero output, performs no storage/waveform/encoding work, and marks
missing or non-finite input invalid. Each `CapturePassage` freezes its offset and
song-clock anchor, and every chunk keeps that offset as `captureOffset`. Stop
fixes the requested song interval before draining its bounded capture tail.
Placement clips corrected samples to that interval. Incomplete capture
preserves the prior audio. The offset is one browser-wide setting
(`localStorage.latency`, ms). Changing it runs `LocalTrack.realign`, which
shifts every chunk by the difference, live during playback; moving back is
lossless, so chunks may reach past the song ends. Restore and `ready()`
re-apply the setting, so stored chunks may lag it. Imported audio has no
`captureOffset` and never moves. No quantization is applied.

`recording-core.js` stores a sparse interval map referencing immutable chunks.
Replacing a passage splits surrounding references without copying the song.
Silence replaces old audio too. Undo retains the last map during this visit.
Import creates chunks at time zero with no capture correction and preserves
remembered audition settings. It validates all samples and duration before
replacing the track. Imports currently accept mono or stereo audio.

`recording-store.js` stores chunks and min/max peaks separately from a track's
interval map, source fingerprint and audition settings. One IndexedDB transaction
publishes each edit and removes unused chunks. Web Locks holds a single writer
per project/version until writes settle or the page closes. A second tab listens
and downloads, but cannot edit. SHA-256 of the fetched source bytes detects
changed sources, independent of bucket-sync timestamps. `sourceIdentity` in the
server index is a size/mtime refresh signal; it is not the saved fingerprint.
A changed source preserves the old track and length, blocks overwriting, and
allows Play back with Solo for recovery before Clear.

Clear invalidates queued operations and writes, aborts pending capture/export,
releases microphone buffers and download URLs, deletes this key's storage after
in-flight transactions, and resets samples, waveform, Undo and audition. It
needs no backing fetch and does not recreate empty metadata on page exit.
Storage failures leave audio in memory with a persistent status message; a read
failure blocks persistence until Clear, preserving any unread saved data.

`recording-export.js` requests 32768-frame batches, uses `recording-wav.js` to
mix/clip/encode 16-bit PCM in a worker, and returns a full-song WAV Blob. It uses
the last qualifying heard backing/gains/solo state with the latest track. Muted
listening, Record and paused control changes do not update that state. Export
has no master-volume input. The encoding still retains the resulting PCM file
in memory, and decoding/import can temporarily hold both input and chunk data.
Ten-minute desktop measurements are in the handoff; recording on a real phone is untested.

Standalone checks are under `checks/`. Run `node checks/recording-core.mjs`,
`node checks/recording-grid.mjs` and `node checks/recording-worklet.mjs` for
sample placement, bar/lead-in arithmetic and processor boundaries.
The browser snippets run against the test fixture on port 8766 after initializing
its audio with a real click. `recording-firefox.py` drives them in a fresh headless
Firefox profile with a fake device microphone. On this laptop:

```bash
uv run --no-project --with selenium python checks/recording-firefox.py
```

PinchTab's regular click does not supply user activation in this setup; mouse
down/up does. Bring its dedicated tab to the foreground before testing
MuseScore polling, which intentionally stops on hidden, paused pages. The snippets include three-minute offline timing, exact middle
replacement, WAV round trips, gain/clipping comparison, storage failures,
interruption safety, no recording write requests, and source-change protection.
They establish software behavior, not physical-device latency.
