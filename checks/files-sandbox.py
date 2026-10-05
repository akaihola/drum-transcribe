"""Nothing fetched from a visitor's link may become a page of this site.

Links that lead to a web page (or name a Drive file "x.html") must leave no
file behind, and whatever does lie under the output root is served with
headers that keep its scripts from running (stored XSS via /files/…).

    uv run python checks/files-sandbox.py
"""

import os
import subprocess
import tempfile
import threading
import urllib.request
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError

os.environ.pop("CREATE_PASSWORDS", None)  # the laptop's rules: local links are fine

from drum_transcribe import ingest
from drum_transcribe.serve import AppHandler

PAGE = "<script>document.title = 'pwned'</script>"


def serve(handler) -> str:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{httpd.server_port}"


class Named(SimpleHTTPRequestHandler):
    """A link server that names its downloads, as Drive does."""

    def end_headers(self):
        self.send_header("Content-Disposition", 'attachment; filename="x.html"')
        super().end_headers()


tmp = Path(tempfile.mkdtemp())
site, root = tmp / "site", tmp / "output"
site.mkdir()
(site / "evil.html").write_text(PAGE)
subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=d=1",
                str(site / "tone.wav")], check=True)
links = serve(partial(Named, directory=str(site)))

for n, (url, ok) in enumerate([
    (f"{links}/tone.wav", True),
    (f"{links}/tone.wav?drive.google.com", True),  # via gdown
    (f"{links}/evil.html", False),
    (f"{links}/evil.html?drive.google.com", False),
    (f"{links}/evil.html?youtube.com", False),  # via yt-dlp
]):
    vdir = root / "song" / f"v{n}"
    vdir.mkdir(parents=True)
    try:
        source = ingest._fetch(vdir, url, None)
    except Exception:  # noqa: BLE001 - which error does not matter here
        source = None
    left = sorted(p.name for p in vdir.iterdir())
    want = ["pipeline.log", "source.flac"] if ok else ["pipeline.log"]
    assert left == want and (source is not None) == ok, (url, left)
    print(f"ok  {url.removeprefix(links)} leaves {left}")

vdir = root / "song" / "v0"
for name, body in [("planted.html", PAGE), ("planted.svg",
                   f'<svg xmlns="http://www.w3.org/2000/svg">{PAGE}</svg>')]:
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
