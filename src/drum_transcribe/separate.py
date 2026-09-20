"""Stage 1: isolate the drums stem from the full mix with Demucs (htdemucs)."""

from pathlib import Path


def separate_drums(audio: Path, outdir: Path, model: str = "htdemucs") -> Path:
    """Run Demucs two-stem separation; return path to the drums stem WAV."""
    import demucs.separate

    stem_dir = outdir / "stems" / model / audio.stem
    drums = stem_dir / "drums.wav"
    if drums.exists():
        return drums
    demucs.separate.main(
        ["--two-stems", "drums", "-n", model, "-o", str(outdir / "stems"), str(audio)]
    )
    if not drums.exists():
        raise FileNotFoundError(f"Demucs did not produce {drums}")
    return drums
