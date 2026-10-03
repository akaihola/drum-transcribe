"""Stage 1: isolate the drums stem from the full mix with Demucs (htdemucs),
optionally followed by MDX23C DrumSep splitting the kit into six stems."""

from pathlib import Path

# audio-separator output tag -> our instrument name
MDX23C_MODEL = "MDX23C-DrumSep-aufr33-jarredou.ckpt"
MDX23C_STEMS = {
    "kick": "kick",
    "snare": "snare",
    "toms": "tom",
    "hh": "hihat",
    "ride": "ride",
    "crash": "crash",
}


def separate_drums(audio: Path, outdir: Path, model: str = "htdemucs") -> Path:
    """Save drums and accompaniment as lossless FLAC, plus Opus copies for
    playback (about 7x smaller: what the page plays and the GPU worker
    uploads); return the drums FLAC path."""
    stem_dir = outdir / "stems" / model / audio.stem
    drums = stem_dir / "drums.flac"
    # Demucs writes the FLACs in place; a crash mid-file would leave both
    # present, so only this marker, written last, means the stage finished
    done = stem_dir / "done"
    if done.exists():
        return drums

    import demucs.separate

    demucs.separate.main(
        ["--two-stems", "drums", "--other-method", "add", "--flac", "--int24",
         "-n", model, "-o", str(outdir / "stems"), str(audio)]
    )
    for stem in (drums, stem_dir / "no_drums.flac"):
        if not stem.exists():
            raise FileNotFoundError(f"Demucs did not produce {stem}")
        _opus_copy(stem)
    done.touch()
    return drums


def _opus_copy(flac: Path) -> None:
    import librosa
    import soundfile as sf

    # Opus only takes 48 kHz (or lower); sonify.py's setting, ~110 kbps a channel
    y, sr = librosa.load(str(flac), sr=48000, mono=False)
    sf.write(str(flac.with_suffix(".ogg")), y.T, sr, format="OGG", subtype="OPUS",
             compression_level=0.6)


def separate_kit_mdx23c(drums_stem: Path, outdir: Path, model_dir: Path) -> dict[str, Path]:
    """Split a drums-only recording into per-drum stems with MDX23C DrumSep.

    Returns {instrument: stem path}. Roughly 10x slower than real time on CPU.
    """
    stem_dir = outdir / "stems" / "mdx23c"
    cached = {
        name: found[0]
        for name in MDX23C_STEMS.values()
        if (found := sorted(stem_dir.glob(f"{name}.*")))
    }
    if len(cached) == len(MDX23C_STEMS):
        return cached
    result = {name: stem_dir / f"{name}.flac" for name in MDX23C_STEMS.values()}

    from audio_separator.separator import Separator

    stem_dir.mkdir(parents=True, exist_ok=True)
    separator = Separator(
        output_dir=str(stem_dir), model_file_dir=str(model_dir), log_level=40,
        output_format="FLAC",
    )
    separator.load_model(model_filename=MDX23C_MODEL)
    produced = separator.separate(str(drums_stem))
    for f in produced:
        path = Path(f) if Path(f).is_absolute() else stem_dir / f
        for tag, name in MDX23C_STEMS.items():
            if f"({tag})" in path.name:
                path.rename(result[name].with_suffix(path.suffix))
                if path.suffix != ".flac":
                    result[name] = result[name].with_suffix(path.suffix)
    missing = [n for n, p in result.items() if not p.exists()]
    if missing:
        raise FileNotFoundError(f"MDX23C did not produce stems: {missing}")
    return result
