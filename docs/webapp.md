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
| `POST /api/feedback` | set/delete one feedback entry, returns variant's map |
| `POST /api/rawbars` | `{project, version, raw}` → flip `keep-raw-bars` flag, re-run |
| `POST /api/seek` | `{bar}` from the MuseScore plugin → bump seq; same bar twice flips `playing` |
| `GET /api/seek` | current `{seq, bar, playing}`; pages poll it every 1 s |
| `GET /files/**` | static from the output root |

`scan_output` also derives per-version: `done`, `error` (log tail contains
"ERROR:"), `stage` (last `== … ==` log marker), the `steps` checklist from
artifact existence, and `irregular`/`raw_bars` — whether `regularize()`
would change the raw beat grid (then the page shows the "uneven bars are
real" checkbox) and whether the `keep-raw-bars` flag file is set. Flipping
the checkbox POSTs `/api/rawbars`, which starts `start_rerun_job`: re-runs
the pipeline for each variant that has `onsets.json`; cached stages make
this take seconds, but note it renumbers bars, which orphans feedback keys.

## Ingestion jobs (ingest.py)

Daemon thread per new version: fetch (yt-dlp for YouTube, gdown fuzzy for
Drive share links, urllib otherwise; ffmpeg -vn extracts audio from video or
unknown containers) → run `python -m drum_transcribe.cli run` per variant
(adtof first for fast feedback), everything appended to
`<version>/pipeline.log`. Failures land in the log as `ERROR: …`.

The new-version form's "process on a rented cloud GPU" checkbox sets
`gpu`: the source is still fetched locally (so all link types and uploads
work), then uploaded to the results bucket, presigned (boto3 via
`uv run --with boto3`, credentials from `.secrets.worker-s3.json`), and
handed to `deploy/run-on-gpu.sh` — rent, process all variants, sync into
the same `output/<song>/<version>/`, destroy. The script's `== … ==`
stage lines go to `pipeline.log`, so the page's stage indicator works;
the artifact checklist fills only when results sync back at the end
(and `stems/` are not synced, so no drums-stem player). See
[gpu-workers.md](gpu-workers.md).

## Front-end notes

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
- Tabs are generic: `.tabs > .tabbar button[data-target]` +
  `.tabs > .tabpanel#id`; `:scope >` selectors keep nested tabs (versions ⊃
  score variants) independent.

## Feedback

Stored per variant in `feedback.json`:
`{"<bar>:<symbol-index>": {"labels": [...], "text": "..."}, "title": {...}}`
where symbol-index counts `g.note, g.rest` in document order within the
measure — stable across reloads for identical score files, NOT stable if a
pipeline re-run changes the notation. Empty labels+text deletes the entry.
UI: hover → blue; saved → orange + SVG `<title>` tooltip; `g.pgHead` click
= whole-transcription feedback.
