# Web app internals (serve.py + ingest.py)

Stdlib-only `ThreadingHTTPServer`; HTML/JS lives in template strings inside
`serve.py`. No state besides the `output/` tree — every page render rescans
the filesystem (plus, for live progress, `ingest.RUNNING`: the version
dirs whose job thread is alive in this process). All
responses carry `Cache-Control: no-cache` (re-runs replace files in place;
without it browsers heuristically cache and render stale scores), and
`/files/**` supports byte ranges (Chromium won't seek audio otherwise).

## Routes

| route | what |
|---|---|
| `GET /` | main page: project list + create form |
| `GET /p/<project>` | project page: version tabs, players, scores, feedback |
| `GET /api/index` | JSON of projects → versions → variants (from `scan_output`) |
| `POST /api/create` | `{project, version, url, gpu?}` → slugify, start background job |
| `PUT /api/upload?project&version&filename&gpu=1?` | raw file body (no multipart) → job |
| `POST /api/unlock` | `{password}` → scrypt check → bypass cookie (see Throttling) |
| `POST /api/feedback` | set/delete one feedback entry, returns variant's map (gated) |
| `POST /api/rawbars` | `{project, version, raw}` → flip `keep-raw-bars` flag, re-run (gated) |
| `POST /api/seek` | `{bar}` from the MuseScore plugin → bump seq; same bar twice flips `playing` |
| `GET /api/seek` | current `{seq, bar, playing}`; pages poll it every 1 s |
| `GET /api/progress?project=` | per version: `progress.version_progress` (see Live progress); polled every 2 s while a job runs |
| `GET /files/**` | static from the output root |

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
results (`/api/feedback`, `/api/rawbars`) need the unlock cookie outright,
only where the `CREATE_PASSWORDS` env var is set — in practice the cloud
container; the laptop server stays unlimited. Design notes (all forced by
the serverless platform: scale-to-zero kills memory, instances don't share
it):

- **Global cap, no per-IP state**: at most `THROTTLE_MAX` (3) anonymous
  creations per `THROTTLE_HOURS` (24), counted from `created` marker files
  in the version dirs. The timestamp is in the file *content* — mtimes lie
  after every bucket re-sync. Markers are best-effort uploaded to the
  bucket at creation so cold starts still see them. `auth` markers (created
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

The new-version form's "process on a rented cloud GPU" checkbox sets
`gpu`: the source is still fetched locally (so all link types and uploads
work), then uploaded to the results bucket, presigned (boto3 via
`uv run --with boto3`, credentials from `.secrets.worker-s3.json`), and
handed to `deploy/run-on-gpu.sh` — rent (or reuse an open
`gpu-session.sh` instance), process all variants, sync into
the same `output/<song>/<version>/`, destroy unless the session owns it. The scripts' stage
lines (and the worker's, streamed over ssh) go to `pipeline.log`, so the
progress bars work for GPU jobs too, plus a "cloud GPU" bar for the
rental start; the result files arrive only when results sync back at
the end, so finished pipelines show a full bar saying so meanwhile. This works both
on the laptop and in the cloud container (which has no `uv`: the scripts
and the presign step fall back to plain `python3`/`vastai`). See
[gpu-workers.md](gpu-workers.md).

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
- Click-to-play: clicking an empty spot in a bar seeks the version's audio
  to that bar and plays. Measures are hit-tested by `getBoundingClientRect`
  at click time (hidden tabs have no layout, so rects can't be precomputed);
  note/rest clicks keep opening the feedback menu instead. Player choice
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
- The project page is a flow diagram per version, three rows on a 4-column
  grid: original —Demucs→ drums stem; drums stem —ADTOF→ adtof and
  —MDX23C→ mdx23c; both of those → fused (centred below; "hits" from ADTOF,
  "6 drum tracks" from the MDX23C kit split). Pipeline cards hold the
  sonification player (slimmed to 2rem) with small download tiles on the
  same line (`.soniline`): the MuseScore and MusicXML logos, served from
  `src/drum_transcribe/static/` at `/static/`, a MIDI plug, and braces for
  JSON; the tooltip names the file; drag-out downloadable via `DownloadURL`. Arrows are an SVG overlay drawn from live
  element positions (`drawArrows`) — redrawn on tab switches and resizes
  because hidden panels have no layout. Players stretch to the card width;
  Chromium's per-player volume controls are hidden in favour of one shared
  `.vol` slider (remembered in `localStorage`). Players are `preload="none"`
  until their version tab is shown (`showPanel` flips them to `metadata`),
  so durations appear without fetching ~0.4 MB per file for hidden tabs. Every title has
  an `i` popover (`INFO`/`infoBtn`) explaining the artifact. Anything not
  ready has a progress bar (`progBar`) where its player will be; pipeline
  logs are in the `#gear-btn` popover.
- YouTube originals: when `v.youtube` is set, the original node holds a
  `<yt-audio video=ID>` custom element instead of `<audio>`. It wraps the
  IFrame API player behind the `<audio>` surface the page uses (`paused`,
  `currentTime`, `volume`, `play()`, `pause()`, dispatched `play` and a
  250 ms `timeupdate`), and every media lookup uses the `MEDIA` selector
  (`"audio, yt-audio"`), so seekToBar, bar follow, the shared volume and the
  plugin treat it like any player. Seeks and plays before the API is ready
  are queued. Cropping: the iframe is 4.4rem tall — YouTube's compact layout
  at that height puts the progress bar at the top and play/pause in the
  middle — shown through a 2.6rem window offset by .6rem. YouTube autohides
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

## Live progress (progress.py)

Every stage line in `pipeline.log` is `== what == <UTC time>`
(`ingest.marker`; `stage` in gpu-session.sh). `version_progress` takes
the current job's part of the log (after the last `all pipelines
finished`/`ERROR:`), maps each marker to a task (`src`, `gpu`, `drums`,
`adtof`, `mdx23c`, `fused`) and step via `STEPS`, and estimates:

- **Expected step time** = fixed + per-song-second, CPU or GPU column,
  measured 2026-09-22 on atom (60 s clip: Demucs 0.34×, MDX23C 6.5×
  song length, the rest seconds) and guessed for the GPU from the
  gpu-workers.md figures — recalibrate from a timestamped GPU log. The
  image-pull step is `45 s + 2 × 8 GB / host download speed`, the speed
  coming from the `instance …, host downloads at N Mbit/s` lines the
  ssh-wait loop logs (Vast reports no pull progress at all: its
  `status_msg` stays empty and `disk_usage` is -1 while loading).
- **Real progress** overrides the guess where a step prints it: yt-dlp's
  `45.3% of`, tqdm's `45%|` (Demucs on CPU; the GPU worker disables tqdm).
- Past its expected time a step creeps (asymptotically, never to 100 %)
  and says "taking longer than usual"; times left are then unknown.
- Task states: `queued` (hatched, still bar), `running`, `arriving`
  (done on the GPU, files not synced yet), `failed`, `stopped` (log
  unfinished but no job thread — the server restarted). A task with its
  file present gets no bar, also during a meter re-run (old results stay
  playable; the meter shows "recomputing…").

## Feedback

Stored per variant in `feedback.json`:
`{"<bar>:<symbol-index>": {"labels": [...], "text": "..."}, "title": {...}}`
where symbol-index counts `g.note, g.rest` in document order within the
measure — stable across reloads for identical score files, NOT stable if a
pipeline re-run changes the notation. Empty labels+text deletes the entry.
UI: hover → blue; saved → orange + SVG `<title>` tooltip; `g.pgHead` click
= whole-transcription feedback. Stored text is attacker-controlled input:
put it in the DOM via `textContent`/`.value` only — it was once interpolated
into the edit menu's `innerHTML`, where `</textarea><img onerror=…>` ran as
script for whoever clicked the note.
