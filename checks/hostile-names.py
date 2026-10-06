"""Names under the output root that this app did not make never reach the
pages, which put names into HTML as they are (stored XSS). Such names could
come from a rented GPU host, or from anything else that writes there.

    uv run --with "$(grep -E '^playwright[=<>~!]' "$UV_CONSTRAINT")" python checks/hostile-names.py
"""

import json
import tempfile
import threading
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright

from drum_transcribe.serve import AppHandler, scan_output


def evil(n: int) -> str:
    return f"<img src=x onerror=window.pwned={n}>"


def result(vdir: Path, variant: str) -> None:
    (vdir / variant).mkdir(parents=True)
    (vdir / variant / "events.json").write_text(json.dumps({"meter": 4, "events": []}))


root = Path(tempfile.mkdtemp())
song = root / "song" / "v1"
result(song, "adtof")
(song / "source.mp3").write_bytes(b"x")
(song / f'source.">{evil(1)}.mp3').write_bytes(b"x")  # sorts before source.mp3
result(song, evil(2))
(song / "stems" / "htdemucs" / evil(3)).mkdir(parents=True)
(song / "stems" / "htdemucs" / evil(3) / "drums.ogg").write_bytes(b"x")
result(root / "song" / evil(4), "adtof")
result(root / evil(5) / "v1", "adtof")

index = scan_output(root)
assert [p["name"] for p in index["projects"]] == ["song"], index
(v,) = index["projects"][0]["versions"]
assert v["name"] == "v1" and v["source"] == "/files/song/v1/source.mp3", v
assert [x["name"] for x in v["variants"]] == ["adtof"] and v["drums"] is None, v
print("ok  the index leaves out every name the app did not make")

httpd = ThreadingHTTPServer(("127.0.0.1", 0), partial(AppHandler, root=root))
threading.Thread(target=httpd.serve_forever, daemon=True).start()
app = f"http://127.0.0.1:{httpd.server_port}"
with sync_playwright() as pw:
    page = pw.chromium.launch().new_page()
    for path, ready in [("/", "#projects a"), ("/p/song", 'section[data-song="v1"]')]:
        page.goto(app + path)
        page.wait_for_selector(ready)
        page.wait_for_timeout(1000)  # time for a planted <img> to fail and fire
        assert page.evaluate("window.pwned") is None, (path, page.evaluate("window.pwned"))
        print(f"ok  {path} runs no planted script in Chromium")
