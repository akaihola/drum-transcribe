"""Create project versions from uploads or URLs; run pipelines in background.

Each version job appends to <version_dir>/pipeline.log; the web page shows
progress by rescanning which artifacts exist on reload.
"""

from __future__ import annotations

import ipaddress
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from . import gate

AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".opus", ".aac", ".aiff"}
VARIANTS = ("adtof", "mdx23c", "fused")
RUNNING: set[Path] = set()  # version dirs with a job thread going (progress.py)
FETCH_LIMIT = 15 * 60  # s for a recording's download, and again for its conversion


def marker(what: str) -> str:
    """A stage line for pipeline.log; progress.py times the steps by it."""
    return f"== {what} == {datetime.now(UTC):%Y-%m-%dT%H:%M:%SZ}"


def start_version_job(version_dir: Path, url: str | None = None,
                      upload: Path | None = None) -> None:
    """Process on this machine's CPU (cloud GPU jobs: coordinator.py)."""
    _start(_job, version_dir, url, upload)


def _start(job, version_dir: Path, *args) -> None:
    def run():
        try:
            job(version_dir, *args)
        finally:
            RUNNING.discard(version_dir)

    RUNNING.add(version_dir)
    threading.Thread(target=run, daemon=True).start()


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


def _run_variant(version_dir: Path, source: Path, variant: str) -> None:
    title = f"{version_dir.parent.name} / {version_dir.name} [{variant}]"
    with open(version_dir / "pipeline.log", "a") as logf:
        subprocess.run(
            [sys.executable, "-m", "drum_transcribe.cli", "run", str(source),
             "-o", str(version_dir), "--variant", variant, "--title", title],
            stdout=logf, stderr=logf, check=True, env=_env(),
        )


def _job(version_dir: Path, url: str | None, upload: Path | None) -> None:
    version_dir.mkdir(parents=True, exist_ok=True)
    try:
        source = _fetch(version_dir, url, upload)
        for variant in VARIANTS:
            _run_variant(version_dir, source, variant)
        _log(version_dir, marker("all pipelines finished"))
    except Exception as e:  # noqa: BLE001 - surfaced via the log on the page
        _log(version_dir, f"ERROR: {e!r}")


def prepare(version_dir: Path, rec: dict) -> None:
    """Fetch a cloud GPU job's recording and publish it for the worker as
    sources/<job>/source.<ext> in the results bucket. One object upload, so
    it appears complete or not at all. Repeatable: after a restart it starts
    over from the saved link or the uploaded original."""
    version_dir.mkdir(parents=True, exist_ok=True)
    for stale in version_dir.glob("fetched.*"):  # an interrupted earlier try
        stale.unlink()
    s3, bucket = gate.results_bucket()
    if rec["upload"]:
        fetched = version_dir / Path(rec["upload"]).name
        if not fetched.exists():  # uploaded to an earlier container
            s3.download_file(bucket, rec["upload"], str(fetched))
    else:
        fetched = _download(version_dir, rec["url"])
    source = _as_source(version_dir, fetched)
    _log(version_dir, marker("handing the recording to the cloud"))
    s3.upload_file(str(source), bucket, f"sources/{rec['job']}/{source.name}")


def start_rerun_job(version_dir: Path) -> None:
    """Regenerate results after a setting change; cached stages make it fast."""
    _start(_rerun, version_dir)


def _rerun(version_dir: Path) -> None:
    try:
        source = next(version_dir.glob("source.*"))
        for variant in VARIANTS:
            if (version_dir / variant / "onsets.json").exists():
                _run_variant(version_dir, source, variant)
        _log(version_dir, marker("all pipelines finished"))
    except Exception as e:  # noqa: BLE001 - surfaced via the log on the page
        _log(version_dir, f"ERROR: {e!r}")


def _fetch(version_dir: Path, url: str | None, upload: Path | None) -> Path:
    """Obtain the source recording as <version_dir>/source.<ext>."""
    if upload is not None:
        return _as_source(version_dir, upload)
    assert url is not None
    return _as_source(version_dir, _download(version_dir, url))


def check_url(url: str) -> str:
    """Refuse links that would make the server read its own network.

    Everything the fetchers download is served back from ``/files/…``, so a
    link is a read primitive. ``file://`` and ``ftp://`` (which urllib,
    yt-dlp and gdown all open) would hand a visitor the server's own files —
    ``/proc/self/environ`` holds every secret at once.

    On the public deployment — the one with the creation throttle switched
    on — host names are resolved too, so nobody can aim it at ``localhost``
    or a neighbour in the datacentre network. The laptop server skips that
    half: fetching from the home LAN or the tailnet is normal there.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("only http:// and https:// links can be fetched")
    if gate.enabled():
        _check_public_host(parsed.hostname)
    return url


def _check_public_host(host: str | None) -> None:
    """Every address ``host`` resolves to must be out on the internet."""
    if not host:
        raise ValueError("that link has no server name")
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(host, None)}
    except socket.gaierror as e:
        raise ValueError(f"cannot find the server {host}") from e
    for address in addresses:
        if not ipaddress.ip_address(address).is_global:
            raise ValueError(f"{host} is inside a private network "
                             f"({address}); links must be public")


class _CheckedRedirect(urllib.request.HTTPRedirectHandler):
    """Re-check every hop: a public link can redirect inwards."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _download(version_dir: Path, url: str) -> Path:
    check_url(url)
    if "youtube.com" in url or "youtu.be" in url:
        _log(version_dir, marker("downloading the recording with yt-dlp"))
        _log(version_dir, f"   {url}")
        with open(version_dir / "pipeline.log", "a") as logf:
            subprocess.run(
                [sys.executable, "-m", "yt_dlp", "-f", "bestaudio", "-x",
                 "--audio-format", "mp3", "--audio-quality", "0",
                 "-o", str(version_dir / "fetched.%(ext)s"), url],
                stdout=logf, stderr=logf, check=True, timeout=FETCH_LIMIT,
            )
        return next(version_dir.glob("fetched.*"))
    if "drive.google.com" in url:
        _log(version_dir, marker("downloading the recording with gdown"))
        _log(version_dir, f"   {url}")
        import gdown

        name = gdown.download(url=url, output=f"{version_dir}/", fuzzy=True, quiet=True)
        if not name:
            raise RuntimeError("Google Drive download failed (is the link public?)")
        return Path(name)
    _log(version_dir, marker("downloading the recording"))
    _log(version_dir, f"   {url}")
    suffix = Path(url.split("?")[0]).suffix or ".bin"
    fetched = version_dir / f"fetched{suffix}"
    opener = urllib.request.build_opener(_CheckedRedirect)
    give_up = time.monotonic() + FETCH_LIMIT
    with opener.open(url, timeout=60) as r, open(fetched, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
            if time.monotonic() > give_up:
                raise TimeoutError(f"download took over {FETCH_LIMIT // 60} min")
    return fetched


def _as_source(version_dir: Path, fetched: Path) -> Path:
    if fetched.suffix.lower() in AUDIO_EXTS:
        source = version_dir / f"source{fetched.suffix.lower()}"
        if fetched != source:
            fetched.rename(source)
        return source

    # video or unknown container: extract/convert the audio track
    _log(version_dir, marker(f"extracting audio from {fetched.name} with ffmpeg"))
    source = version_dir / "source.m4a"
    with open(version_dir / "pipeline.log", "a") as logf:
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(fetched), "-vn", "-ac", "2", str(source)],
            stdout=logf, stderr=logf, check=True, timeout=FETCH_LIMIT,
        )
    return source
