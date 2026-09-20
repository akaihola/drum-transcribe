"""Pipeline CLI: audio in, drum notation out, with inspectable intermediates.

    drum-transcribe run song.mp3 -o output/song

writes into the output directory:
    stems/<model>/<song>/drums.wav   separated drums stem
    beats.json                       beat/downbeat grid
    onsets.json                      detected hits with confidence + velocity
    events.json                      quantized events (bar/beat fractions)
    audition.mid                     quantized MIDI at real-time positions
    score.musicxml                   drum staff for MuseScore etc.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="drum-transcribe", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run the full pipeline")
    run.add_argument("audio", type=Path)
    run.add_argument("-o", "--outdir", type=Path, default=None)
    run.add_argument("--title", default=None, help="score title")
    run.add_argument(
        "--no-separate",
        action="store_true",
        help="transcribe the input directly (already a drums-only recording)",
    )
    run.add_argument(
        "--from-stage",
        choices=["separate", "beats", "transcribe", "quantize", "score"],
        default="separate",
        help="resume from this stage, reusing earlier artifacts in outdir",
    )

    srv = sub.add_parser("serve", help="review UI web server for a pipeline output dir")
    srv.add_argument("outdir", type=Path)
    srv.add_argument("--audio", type=Path, default=None, help="original recording")
    srv.add_argument("--host", default="0.0.0.0")
    srv.add_argument("--port", type=int, default=8765)

    args = parser.parse_args(argv)

    if args.command == "serve":
        from .serve import serve

        serve(args.outdir, original=args.audio, host=args.host, port=args.port)
        return 0

    audio: Path = args.audio
    outdir: Path = args.outdir or Path("output") / audio.stem
    outdir.mkdir(parents=True, exist_ok=True)
    stages = ["separate", "beats", "transcribe", "quantize", "score"]
    start = stages.index(args.from_stage)

    def stage_enabled(name: str) -> bool:
        return stages.index(name) >= start

    from .audition import write_audition_midi
    from .beats import BeatGrid, track_beats
    from .quantize import load_events, quantize, save_events
    from .score import write_musicxml
    from .separate import separate_drums
    from .transcribe import (
        detect_onsets,
        estimate_velocities,
        load_onsets,
        save_onsets,
    )

    beats_json = outdir / "beats.json"
    onsets_json = outdir / "onsets.json"
    events_json = outdir / "events.json"

    if args.no_separate:
        drums_stem = audio
    else:
        print("== separating drums stem (Demucs) ==", flush=True)
        drums_stem = separate_drums(audio, outdir)
        print(f"   {drums_stem}")

    if stage_enabled("beats") or not beats_json.exists():
        print("== tracking beats/downbeats (beat_this) ==", flush=True)
        grid = track_beats(audio)
        grid.save(beats_json)
    else:
        grid = BeatGrid.load(beats_json)
    print(f"   {len(grid.times)} beats, meter {grid.meter}/4")

    if stage_enabled("transcribe") or not onsets_json.exists():
        print("== detecting drum hits (ADTOF) ==", flush=True)
        onsets, _act = detect_onsets(drums_stem)
        estimate_velocities(onsets, drums_stem)
        save_onsets(onsets, onsets_json)
    else:
        onsets = load_onsets(onsets_json)
    print(f"   {len(onsets)} onsets")

    if stage_enabled("quantize") or not events_json.exists():
        print("== quantizing to grid ==", flush=True)
        events = quantize(onsets, grid)
        save_events(events, grid.meter, events_json)
    else:
        events, _meter = load_events(events_json)
    big_err = [e for e in events if abs(e.error_ms) > 35]
    print(f"   {len(events)} events; {len(big_err)} with >35 ms quantization error")

    print("== writing outputs ==", flush=True)
    from .sonify import write_sonification

    write_audition_midi(events, outdir / "audition.mid")
    write_sonification(events, audio, outdir / "sonification.wav")
    title = args.title or audio.stem
    write_musicxml(events, grid.meter, outdir / "score.musicxml", title=title)
    for name in ("audition.mid", "sonification.wav", "score.musicxml"):
        print(f"   {outdir / name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
