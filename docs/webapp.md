# Web app internals (serve.py + ingest.py)

Stdlib-only `ThreadingHTTPServer`; HTML/JS lives in template strings inside
`serve.py`. No state besides the `output/` tree — every page render rescans
the filesystem, which is what makes "reload to see progress" work. All
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
| `POST /api/feedback` | set/delete one feedback entry, returns variant's map |
| `POST /api/rawbars` | `{project, version, raw}` → flip `keep-raw-bars` flag, re-run |
| `POST /api/seek` | `{bar}` from the MuseScore plugin → bump seq; same bar twice flips `playing` |
| `GET /api/seek` | current `{seq, bar, playing}`; pages poll it every 1 s |
| `GET /files/**` | static from the output root |

`scan_output` also derives per-version: `done`, `error` (log tail contains
"ERROR:"), `stage` (last `== … ==` log marker), the `steps` checklist from
artifact existence, and `irregular`/`raw_bars` — whether `regularize()`
would change the raw beat grid (then the meter switch above the score is
enabled) and whether the `keep-raw-bars` flag file is set. Switching the
meter option POSTs `/api/rawbars`, which starts `start_rerun_job`: re-runs
the pipeline for each variant that has `onsets.json`; cached stages make
this take seconds, but note it renumbers bars, which orphans feedback keys.

## Throttling (gate.py)

Creation (`/api/create`, `/api/upload`) is throttled only where the
`CREATE_PASSWORDS` env var is set — in practice the cloud container; the
laptop server stays unlimited. Design notes (all forced by the serverless
platform: scale-to-zero kills memory, instances don't share it):

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
- **Token**: stateless — `HMAC(TOKEN_SECRET, salt of the matched entry)`.
  Deleting a person's entry revokes their tokens; rotating `TOKEN_SECRET`
  revokes all. Brute force is answered with passphrase entropy (~72 bits)
  plus a 1 s delay on failure, not with lockout counters (which would be a
  DoS button and need durable state anyway).

Daemon thread per new version: fetch (yt-dlp for YouTube, gdown fuzzy for
Drive share links, urllib otherwise; ffmpeg -vn extracts audio from video or
unknown containers) → run `python -m drum_transcribe.cli run` per variant
(adtof first for fast feedback), everything appended to
`<version>/pipeline.log`. Failures land in the log as `ERROR: …`.

`ingest.check_url` rejects every scheme but `http`/`https`: all three
fetchers happily open `file://`, and on the public server the fetched bytes
are served back from `/files/…` — a visitor could ask for
`/proc/self/environ` and read every secret at once. `POST /api/create`
checks the link first, so a bad one is a 400 with no project directory and
no throttle marker.

The new-version form's "process on a rented cloud GPU" checkbox sets
`gpu`: the source is still fetched locally (so all link types and uploads
work), then uploaded to the results bucket, presigned (boto3 via
`uv run --with boto3`, credentials from `.secrets.worker-s3.json`), and
handed to `deploy/run-on-gpu.sh` — rent (or reuse an open
`gpu-session.sh` instance), process all variants, sync into
the same `output/<song>/<version>/`, destroy unless the session owns it. The script's `== … ==`
stage lines go to `pipeline.log`, so the page's stage indicator works;
the artifact checklist fills only when results sync back at the end
(and `stems/` are not synced, so no drums-stem player). This works both
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
- The project page is a flow diagram per version: original —Demucs→ drums
  stem (stacked vertically) → one card per pipeline (sonification + file-type
  logo icons beside the player; drag-out downloadable via `DownloadURL`).
  Arrows are an SVG overlay drawn from live element positions (`drawArrows`),
  labeled with the model that produced each derivation — redrawn on tab
  switches and resizes because hidden panels have no layout. Every title has
  an `i` popover (`INFO`/`infoBtn`) explaining the artifact. Anything not
  ready is dimmed (`.waiting .dimmable`) with a spinner whose `title`
  explains the step; pipeline logs are in the `#gear-btn` popover.

## Feedback

Stored per variant in `feedback.json`:
`{"<bar>:<symbol-index>": {"labels": [...], "text": "..."}, "title": {...}}`
where symbol-index counts `g.note, g.rest` in document order within the
measure — stable across reloads for identical score files, NOT stable if a
pipeline re-run changes the notation. Empty labels+text deletes the entry.
UI: hover → blue; saved → orange + SVG `<title>` tooltip; `g.pgHead` click
= whole-transcription feedback.
