# drum-transcribe — agent guide

Forensic drum transcription: recording in → drum sheet music + review web app.
Working, deployed on this laptop (`atom`), all results committed to `output/`
conventions described below. Read [CLAUDE.md](CLAUDE.md) for binding project
rules (non-developer user, Honey/minimal style, web-first interaction,
frequent commits).

## Commands

```bash
uv sync                                   # CC sandbox: CC=$(readlink -f $(which gcc)) uv sync
uv run drum-transcribe run SONG.mp3 --variant adtof|mdx23c|fused -o output/PROJECT/VERSION
uv run drum-transcribe serve output --port 8765   # must run OUTSIDE the CC sandbox (see below)
```

No test suite; verify by running the pipeline on `output/dancing-through-life/taustanauha/source.mp3`
(all stages cached → seconds) and by driving the web UI with PinchTab.

The server runs as a systemd user service: `systemctl --user status drum-transcribe`.
Restart it after editing `serve.py`/`ingest.py`: `systemctl --user restart drum-transcribe`.

## Code map (src/drum_transcribe/)

| module | job |
|---|---|
| `cli.py` | `run` (pipeline per variant) and `serve` subcommands |
| `separate.py` | Demucs drums stem; MDX23C 6-stem kit split |
| `beats.py` | beat_this beat/downbeat grid (`BeatGrid`); `regularize()` barline repair |
| `transcribe.py` | ADTOF onsets + stem-energy velocities; per-stem onset detection |
| `quantize.py` | onsets → `Event` list on per-beat straight/triplet grid |
| `score.py` | events → MusicXML drum staff (MuseScore-compatible; see below) |
| `audition.py`, `sonify.py` | quantized MIDI; original + blips WAV |
| `export.py` | best-effort MusicXML → .mscz |
| `ingest.py` | URL/upload fetch + background pipeline jobs |
| `serve.py` | web app: pages, API, score feedback |
| `gate.py` | creation throttle for the cloud webapp: password unlock, bypass cookie |

## Data layout

`output/<project>/<version>/` holds `source.*`, `beats_raw.json` (tracker
output), `beats.json` (effective grid: barlines repaired unless a
`keep-raw-bars` flag file is present), `pipeline.log`,
`stems/htdemucs/source/drums.wav`, `stems/mdx23c/*.wav`, and per variant
(`adtof/`, `mdx23c/`, `fused/`): `onsets.json`, `events.json`, `audition.mid`,
`sonification.wav`, `score.musicxml`, `score.mscz?`, `feedback.json?`.
Model caches: `.cache/` (torch, HF) and `.models/` (MDX23C), both gitignored.

## Deep dives (read when touching that area)

- [docs/architecture.md](docs/architecture.md) — pipeline design and the reasons behind it
- [docs/notation-musescore.md](docs/notation-musescore.md) — **read before touching score.py**; hard-won MuseScore import constraints
- [docs/webapp.md](docs/webapp.md) — pages, API endpoints, feedback storage format
- [docs/musescore-plugin.md](docs/musescore-plugin.md) — play-from-bar MuseScore plugin (musescore/PlayFromBar.qml) + server design
- [docs/operations.md](docs/operations.md) — running on atom: sandbox, firewall, systemd, caches; cloud web app copy
- [docs/gpu-workers.md](docs/gpu-workers.md) — processing songs on rented cloud GPUs (image, worker, bucket, Vast.ai)
- [docs/roadmap.md](docs/roadmap.md) — current state, known issues, agreed next steps
- [docs/adt-landscape.md](docs/adt-landscape.md) — 2026 tool survey the stack was chosen from
