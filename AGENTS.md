# drum-transcribe — agent guide

Forensic drum transcription: recording in → drum sheet music + review web app.
Working, deployed on this laptop (`atom`), all results committed to `output/`
conventions described below. The project rules below are binding.

Issues are tracked in [TASKS.md](TASKS.md). Follow its rules for scheduling,
progress, completion and user acceptance.

## Project rules

- The user is a musician, not a software developer. Keep all documentation
  (especially README.md) up to date and understandable without programming
  knowledge — explain what each output (e.g. the sonification) *is*.
- Follow the Honey skill: minimum code that needs to exist, clean and minimal
  architecture, easy to maintain. No speculative features.
- Any step where the user listens, looks, or corrects results must be a web
  server bound to 0.0.0.0, reachable from other machines.
- Commit frequently, in small logical parts.
- Results from different pipeline variants and different songs stay in
  separate directories: `output/<song>/<variant>/`.
- Missing tools on this NixOS laptop: run via comma, e.g. `, mscore`.
- Develop in agent@gogo's clone. Heavy testing and all deployment run in
  akaihola@atom's clone `~/prg/drum-transcribe` (a global rule), the only
  clone with the models, results and Python environment.

## Commands

```bash
uv sync                                   # CC sandbox: CC=$(readlink -f $(which gcc)) uv sync
uv run drum-transcribe run SONG.mp3 --variant adtof|mdx23c|fused -o output/PROJECT/VERSION
uv run drum-transcribe serve output --port 8765   # must run OUTSIDE the CC sandbox (see below)
```

No test suite; verify by running the pipeline on `output/dancing-through-life/taustanauha/source.mp3`
(all stages cached → seconds) and by driving the web UI with PinchTab.
Downloads and `/files/` must never become pages of the site (stored XSS):
`LD_LIBRARY_PATH=$NIX_LD_LIBRARY_PATH uv run python checks/files-sandbox.py`.
Names the app didn't make (project, version, variant, source, stem dirs)
must stay off the pages, checked in Chromium:
`uv run --with "$(grep -E '^playwright[=<>~!]' "$UV_CONSTRAINT")" python checks/hostile-names.py`.
The cloud GPU job logic has mocked checks:
`LD_LIBRARY_PATH=$NIX_LD_LIBRARY_PATH uv run --with boto3 python checks/gpu-jobs.py`
(the library path only inside the Claude Code sandbox, where numpy can't
find libstdc++ otherwise). What only real rentals show runs on atom with
`checks/gpu-rentals.py` (a few cents per song; how-to in its docstring).

The server runs as a systemd user service: `systemctl --user status drum-transcribe`.
Restart it after editing `serve.py`/`ingest.py`: `systemctl --user restart drum-transcribe`
— then check it took (`ss -tlnp | grep 8765`); see operations.md → The server.

## Code map (src/drum_transcribe/)

| module | job |
|---|---|
| `cli.py` | `run` (pipeline per variant), `serve`, and `hash-password` subcommands |
| `separate.py` | Demucs drums stem; MDX23C 6-stem kit split |
| `beats.py` | beat_this beat/downbeat grid (`BeatGrid`); `regularize()` barline repair |
| `transcribe.py` | ADTOF onsets + stem-energy velocities; per-stem onset detection |
| `quantize.py` | onsets → `Event` list on per-beat straight/triplet grid |
| `score.py` | events → MusicXML drum staff (MuseScore-compatible; see below) |
| `audition.py`, `sonify.py` | quantized MIDI; original + blips WAV |
| `export.py` | MusicXML → .mscz; forced with `-f` + `mscz-problems.txt` if refused |
| `ingest.py` | URL/upload fetch + local background pipeline jobs; `prepare` publishes a cloud job's recording; `check_url` vets links (webapp.md) |
| `serve.py` | web app: pages, API, score feedback |
| `gate.py` | cloud webapp gate: creation throttle, password unlock, bypass cookie (edits need it too); results-bucket helpers |
| `jobs.py` | trusted cloud GPU job records in the `drum-transcribe-jobs` bucket (conditional writes) |
| `coordinator.py` | the cloud web app's one rental owner: reconciles records with Vast and the bucket each minute (gpu-workers.md, gpu-resilience-handoff.md) |
| `vast.py` | Vast.ai REST calls, failures split into Rejected / Uncertain |
| `atomic.py` | temp-file-and-rename writes for cached results |

## Data layout

`output/<project>/<version>/` holds `source.*`, `beats_raw.json` (tracker
output), `beats.json` (effective grid: barlines repaired unless a
`keep-raw-bars` flag file is present), `pipeline.log`,
`stems/htdemucs/source/{drums,no_drums}.flac` (no_drums = without-drums
accompaniment) with Opus copies `.ogg` for playback and a `done` marker,
`stems/mdx23c/*.flac`, and per variant
(`adtof/`, `mdx23c/`, `fused/`): `onsets.json`, `events.json`, `audition.mid`,
`sonification.ogg` (Opus), `score.musicxml`, `score.mscz?`, `mscz-problems.txt?`,
`feedback.json?`.
Model caches: `.cache/` (torch, HF) and `.models/` (MDX23C), both gitignored.

## Deep dives (read when touching that area)

- [docs/architecture.md](docs/architecture.md) — pipeline design and the reasons behind it
- [docs/notation-musescore.md](docs/notation-musescore.md) — **read before touching score.py**; hard-won MuseScore import constraints
- [docs/webapp.md](docs/webapp.md) — pages, API endpoints, feedback storage format
- [docs/musescore-plugin.md](docs/musescore-plugin.md) — play-from-bar MuseScore plugin (musescore/PlayFromBar.qml) + server design
- [docs/operations.md](docs/operations.md) — running on atom: sandbox, firewall, systemd, caches; cloud web app copy
- [docs/gpu-workers.md](docs/gpu-workers.md) — processing songs on rented cloud GPUs (image, worker, bucket, Vast.ai)
- [docs/recovery.md](docs/recovery.md) — laptop-loss plan: which secrets go in the password manager, rebuild steps
- [docs/roadmap.md](docs/roadmap.md) — current state, known issues, agreed next steps
- [docs/adt-landscape.md](docs/adt-landscape.md) — 2026 tool survey the stack was chosen from
