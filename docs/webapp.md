# Web app internals (serve.py + ingest.py)

Stdlib-only `ThreadingHTTPServer`; HTML/JS lives in template strings inside
`serve.py`. No state besides the `output/` tree — every page render rescans
the filesystem, which is what makes "reload to see progress" work.

## Routes

| route | what |
|---|---|
| `GET /` | main page: project list + create form |
| `GET /p/<project>` | project page: version tabs, players, scores, feedback |
| `GET /api/index` | JSON of projects → versions → variants (from `scan_output`) |
| `POST /api/create` | `{project, version, url}` → slugify, start background job |
| `PUT /api/upload?project&version&filename` | raw file body (no multipart) → job |
| `POST /api/feedback` | set/delete one feedback entry, returns variant's map |
| `GET /files/**` | static from the output root |

`scan_output` also derives per-version: `done`, `error` (log tail contains
"ERROR:"), `stage` (last `== … ==` log marker), and the `steps` checklist
from artifact existence.

## Ingestion jobs (ingest.py)

Daemon thread per new version: fetch (yt-dlp for YouTube, gdown fuzzy for
Drive share links, urllib otherwise; ffmpeg -vn extracts audio from video or
unknown containers) → run `python -m drum_transcribe.cli run` per variant
(adtof first for fast feedback), everything appended to
`<version>/pipeline.log`. Failures land in the log as `ERROR: …`.

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
  note/rest clicks keep opening the feedback menu instead. Player choice:
  currently playing > last played (`play` events, capture) > first in
  section. `preload="none"` means seek must wait for `loadedmetadata`.
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
