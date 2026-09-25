"""Pipeline CLI: audio in, drum notation out, with inspectable intermediates.

    drum-transcribe run song.mp3 --variant adtof
    drum-transcribe run song.mp3 --variant mdx23c
    drum-transcribe serve output

Output layout (one directory per song, one subdirectory per pipeline variant,
so results from different pipelines never mix):

    output/<song>/source.<ext>                 copy of the input recording
    output/<song>/beats.json                   beat/downbeat grid (shared)
    output/<song>/stems/htdemucs/.../drums.flac separated drums (shared)
    output/<song>/stems/mdx23c/*.flac          per-drum stems (mdx23c variant)
    output/<song>/<variant>/onsets.json        detected hits
    output/<song>/<variant>/events.json        quantized events
    output/<song>/<variant>/audition.mid       quantized MIDI
    output/<song>/<variant>/sonification.ogg   original + synthetic blips (Opus)
    output/<song>/<variant>/score.musicxml     drum staff (MuseScore-ready)
    output/<song>/<variant>/score.mscz         MuseScore file (if converter found)
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

VARIANTS = ("adtof", "mdx23c", "fused")


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="drum-transcribe", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run the full pipeline")
    run.add_argument("audio", type=Path)
    run.add_argument("--variant", choices=VARIANTS, default="adtof",
                     help="adtof: ADTOF neural 5-class transcription; "
                          "mdx23c: 6-stem drum separation + per-stem onsets; "
                          "fused: ADTOF onsets refined with MDX23C stems "
                          "(ride/crash split, per-drum velocities)")
    run.add_argument("-o", "--outdir", type=Path, default=None,
                     help="song output dir (default: output/<song-name>)")
    run.add_argument("--title", default=None, help="score title")
    run.add_argument("--force", action="store_true",
                     help="recompute everything, ignoring cached artifacts")

    srv = sub.add_parser("serve", help="review/compare web UI for pipeline outputs")
    srv.add_argument("root", type=Path, nargs="?", default=Path("output"))
    srv.add_argument("--host", default="0.0.0.0")
    srv.add_argument("--port", type=int, default=8765)

    pw = sub.add_parser("hash-password",
                        help="make a CREATE_PASSWORDS entry for the cloud "
                             "webapp's creation throttle (see docs/webapp.md)")
    pw.add_argument("password", nargs="?", default=None,
                    help="password to hash (default: generate a passphrase)")

    args = parser.parse_args(argv)

    if args.command == "serve":
        from .serve import serve

        serve(args.root, host=args.host, port=args.port)
        return 0

    if args.command == "hash-password":
        from .gate import generate_passphrase, hash_password

        password = args.password or generate_passphrase()
        if len(password) < 12:
            parser.error("password must be at least 12 characters")
        print(f"password: {password}")
        print(f"entry:    {hash_password(password)}")
        print("Append the entry to the container's CREATE_PASSWORDS secret "
              "env var (comma-separated, one entry per person).")
        return 0

    return run_pipeline(args)


def run_pipeline(args: argparse.Namespace) -> int:
    from .ingest import marker

    print(marker(f"running pipeline: {args.variant}"), flush=True)
    from .audition import write_audition_midi
    from .beats import BeatGrid, regularize, track_beats
    from .export import to_mscz
    from .quantize import quantize, save_events
    from .score import write_musicxml
    from .separate import separate_drums, separate_kit_mdx23c
    from .sonify import write_sonification
    from .transcribe import (
        detect_onsets,
        detect_onsets_from_stems,
        estimate_velocities,
        load_onsets,
        refine_with_stems,
        save_onsets,
    )

    audio: Path = args.audio
    song_dir: Path = args.outdir or Path("output") / slugify(audio.stem)
    vdir = song_dir / args.variant
    vdir.mkdir(parents=True, exist_ok=True)

    source = song_dir / f"source{audio.suffix}"
    if not source.exists():
        shutil.copy2(audio, source)

    print(f"song: {song_dir.name}  variant: {args.variant}", flush=True)

    print(marker("separating drums stem (Demucs htdemucs)"), flush=True)
    drums_stem = separate_drums(source, song_dir)
    print(f"   {drums_stem}")

    # beats_raw.json caches the tracker output; beats.json is the effective
    # grid used everywhere: barlines repaired by default, raw if the user
    # asserted (via the web UI's keep-raw-bars flag) that unequal bars are real.
    beats_raw = song_dir / "beats_raw.json"
    beats_json = song_dir / "beats.json"
    if not beats_raw.exists() and beats_json.exists():
        shutil.copy2(beats_json, beats_raw)  # pre-repair output: beats.json was raw
    if beats_raw.exists() and not args.force:
        raw = BeatGrid.load(beats_raw)
    else:
        print(marker("tracking beats/downbeats (beat_this)"), flush=True)
        raw = track_beats(source)
        raw.save(beats_raw)
    keep_raw = (song_dir / "keep-raw-bars").exists()
    grid = raw if keep_raw else regularize(raw)
    grid.save(beats_json)
    print(f"   {len(grid.times)} beats, meter {grid.meter}/4"
          + (" (raw barlines kept)" if keep_raw else ""))

    onsets_json = vdir / "onsets.json"
    if onsets_json.exists() and not args.force:
        onsets = load_onsets(onsets_json)
    elif args.variant == "mdx23c":
        print(marker("splitting kit into 6 stems (MDX23C, slow on CPU)"), flush=True)
        stems = separate_kit_mdx23c(drums_stem, song_dir, model_dir=Path(".models"))
        print(marker("detecting per-stem onsets"), flush=True)
        onsets = detect_onsets_from_stems(stems)
    elif args.variant == "fused":
        print(marker("splitting kit into 6 stems (MDX23C, slow on CPU)"), flush=True)
        stems = separate_kit_mdx23c(drums_stem, song_dir, model_dir=Path(".models"))
        print(marker("detecting drum hits (ADTOF)"), flush=True)
        onsets, _act = detect_onsets(drums_stem)
        print(marker("refining with per-drum stems (ride/crash, velocities)"), flush=True)
        refine_with_stems(onsets, stems)
    else:
        print(marker("detecting drum hits (ADTOF)"), flush=True)
        onsets, _act = detect_onsets(drums_stem)
        estimate_velocities(onsets, drums_stem)
    save_onsets(onsets, vdir / "onsets.json")
    print(f"   {len(onsets)} onsets")

    print(marker("quantizing to grid"), flush=True)
    events = quantize(onsets, grid)
    save_events(events, grid.meter, vdir / "events.json")
    big_err = [e for e in events if abs(e.error_ms) > 35]
    print(f"   {len(events)} events; {len(big_err)} with >35 ms quantization error")

    print(marker("writing outputs"), flush=True)
    write_audition_midi(events, vdir / "audition.mid")
    write_sonification(events, source, vdir / "sonification.ogg")
    title = args.title or f"{audio.stem} [{args.variant}]"
    write_musicxml(events, grid.meter, vdir / "score.musicxml", title=title)
    mscz = to_mscz(vdir / "score.musicxml", vdir / "score.mscz")
    for p in sorted(vdir.iterdir()):
        print(f"   {p}")
    if mscz is None:
        print("   (MuseScore conversion failed; score.mscz not written; "
              "MUSESCORE_CMD sets the command, default 'musescore')")
    return 0


if __name__ == "__main__":
    sys.exit(main())
