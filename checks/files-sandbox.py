"""Nothing fetched from a visitor's link may become a page of this site.

A link's download is saved under a name this code chooses, never one the
link or Drive gives ("x.html"); links to web pages leave no file behind; and
whatever does lie under the output root is served with headers that keep
its scripts from running (stored XSS via /files/…).

    uv run python checks/files-sandbox.py
"""

import http.client
import os
import subprocess
import tempfile
import threading
import urllib.request
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError

import gdown

os.environ.pop("CREATE_PASSWORDS", None)  # the laptop's rules: local links are fine

from drum_transcribe import ingest
from drum_transcribe.serve import AppHandler

PAGE = "<script>document.title = 'pwned'</script>"
SVG = f'<svg xmlns="http://www.w3.org/2000/svg">{PAGE}</svg>'


def serve(handler) -> str:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{httpd.server_port}"


def drive(url: str, output: str, quiet: bool) -> str:
    """gdown without the network: given a directory, Drive names the file."""
    path = Path(output, "x.html") if output.endswith("/") else Path(output)
    path.write_text(PAGE)
    return str(path)


def left(vdir: Path) -> list[str]:
    return sorted(p.name for p in vdir.iterdir())


tmp = Path(tempfile.mkdtemp())
site, root = tmp / "site", tmp / "output"
site.mkdir()
(site / "evil.html").write_text(f'{PAGE}<audio src="evil.svg"></audio>')
(site / "evil.svg").write_text(SVG)
for tone in ["tone.wav", "tone.mp3"]:
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=d=1",
                    str(site / tone)], check=True)
links = serve(partial(SimpleHTTPRequestHandler, directory=str(site)))

for n, (url, source) in enumerate([
    ("/tone.wav", "source.flac"),
    ("/tone.mp3", "source.mp3"),  # lossy audio is kept as it is
    ("/evil.html", None),
    ("/evil.html?youtube.com", None),  # not YouTube: no yt-dlp saving evil.svg
]):
    vdir = root / "song" / f"v{n}"
    vdir.mkdir(parents=True)
    try:
        got = ingest._fetch(vdir, links + url, None).name
    except Exception:  # noqa: BLE001 - which error does not matter here
        got = None
    want = sorted({"pipeline.log", source} - {None})
    assert got == source and left(vdir) == want, (url, got, left(vdir))
    print(f"ok  {url} leaves {want}")

gdown.download = drive
vdir = root / "song" / "drive"
vdir.mkdir()
ingest._download(vdir, "https://drive.google.com/file/d/x/view")
assert left(vdir) == ["fetched.bin", "pipeline.log"], left(vdir)
print("ok  Drive's x.html is saved as fetched.bin")

vdir = root / "song" / "v0"
for name, body in [("planted.html", PAGE), ("planted.svg", SVG)]:
    (vdir / name).write_text(body)
app = serve(partial(AppHandler, root=root))


def headers(path: str, **extra) -> dict:
    req = urllib.request.Request(app + path, headers=extra)
    try:
        with urllib.request.urlopen(req) as r:
            return dict(r.headers) | {"status": r.status}
    except HTTPError as e:
        return dict(e.headers) | {"status": e.code}


for path, extra, status in [
    ("/files/song/v0/planted.html", {}, 200),
    ("/files/song/v0/planted.svg", {}, 200),
    ("/files/song/v0/source.flac", {"Range": "bytes=0-"}, 206),
    ("/files/song/v0/", {}, 200),  # directory listing
    ("/files/song/v0/missing.html", {}, 404),
]:
    h = headers(path, **extra)
    assert h["status"] == status, (path, h)
    assert h["X-Content-Type-Options"] == "nosniff", (path, h)
    assert h["Content-Security-Policy"] == "sandbox; default-src 'none'", (path, h)
    print(f"ok  {path} {status} is sandboxed")
h = headers("/")
assert h["status"] == 200 and "Content-Security-Policy" not in h, h
print("ok  / (the app itself) is not sandboxed")

conn = http.client.HTTPConnection(app.removeprefix("http://"))
conn.putrequest("OPTIONS", "http://[x/", skip_host=True)  # urlparse rejects it
conn.endheaders()
assert conn.getresponse().status == 501
print("ok  a garbled request still gets its error reply")
