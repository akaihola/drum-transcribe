"""Create project versions from uploads or URLs; run pipelines in background.

Each version job appends to <version_dir>/pipeline.log; the web page shows
progress by rescanning which artifacts exist on reload.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path

AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".opus", ".aac", ".aiff"}
VARIANTS = ("adtof", "mdx23c")


def start_version_job(version_dir: Path, url: str | None = None,
                      upload: Path | None = None) -> None:
    threading.Thread(target=_job, args=(version_dir, url, upload), daemon=True).start()


def _log(version_dir: Path, message: str) -> None:
    with open(version_dir / "pipeline.log", "a") as f:
        f.write(message + "\n")


def _env() -> dict[str, str]:
    cache = Path.cwd() / ".cache"
    return {
        **os.environ,
        "TORCH_HOME": str(cache / "torch"),
        "HF_HOME": str(cache / "hf"),
        "XDG_CACHE_HOME": str(cache),
        "MPLCONFIGDIR": os.environ.get("TMPDIR", "/tmp"),
    }


def _job(version_dir: Path, url: str | None, upload: Path | None) -> None:
    version_dir.mkdir(parents=True, exist_ok=True)
    try:
        source = _fetch(version_dir, url, upload)
        title_base = f"{version_dir.parent.name} / {version_dir.name}"
        for variant in VARIANTS:
            _log(version_dir, f"== running pipeline: {variant} ==")
            with open(version_dir / "pipeline.log", "a") as logf:
                subprocess.run(
                    [sys.executable, "-m", "drum_transcribe.cli", "run",
                     str(source), "-o", str(version_dir), "--variant", variant,
                     "--title", f"{title_base} [{variant}]"],
                    stdout=logf, stderr=logf, check=True, env=_env(),
                )
        _log(version_dir, "== all pipelines finished ==")
    except Exception as e:  # noqa: BLE001 - surfaced via the log on the page
        _log(version_dir, f"ERROR: {e!r}")


def _fetch(version_dir: Path, url: str | None, upload: Path | None) -> Path:
    """Obtain the source recording as <version_dir>/source.<ext>."""
    if upload is not None:
        return _as_source(version_dir, upload)
    assert url is not None
    return _as_source(version_dir, _download(version_dir, url))


def _download(version_dir: Path, url: str) -> Path:
    if "youtube.com" in url or "youtu.be" in url:
        _log(version_dir, f"downloading audio with yt-dlp: {url}")
        with open(version_dir / "pipeline.log", "a") as logf:
            subprocess.run(
                [sys.executable, "-m", "yt_dlp", "-f", "bestaudio", "-x",
                 "--audio-format", "mp3", "--audio-quality", "0",
                 "-o", str(version_dir / "fetched.%(ext)s"), url],
                stdout=logf, stderr=logf, check=True,
            )
        return next(version_dir.glob("fetched.*"))
    if "drive.google.com" in url:
        _log(version_dir, f"downloading with gdown: {url}")
        import gdown

        name = gdown.download(url=url, output=f"{version_dir}/", fuzzy=True, quiet=True)
        if not name:
            raise RuntimeError("Google Drive download failed (is the link public?)")
        return Path(name)
    _log(version_dir, f"downloading: {url}")
    import urllib.request

    suffix = Path(url.split("?")[0]).suffix or ".bin"
    fetched = version_dir / f"fetched{suffix}"
    with urllib.request.urlopen(url, timeout=60) as r, open(fetched, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    return fetched


def _as_source(version_dir: Path, fetched: Path) -> Path:
    if fetched.suffix.lower() in AUDIO_EXTS:
        source = version_dir / f"source{fetched.suffix.lower()}"
        if fetched != source:
            fetched.rename(source)
        return source

    # video or unknown container: extract/convert the audio track
    _log(version_dir, f"extracting audio from {fetched.name} with ffmpeg")
    source = version_dir / "source.m4a"
    with open(version_dir / "pipeline.log", "a") as logf:
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(fetched), "-vn", "-ac", "2", str(source)],
            stdout=logf, stderr=logf, check=True,
        )
    return source
