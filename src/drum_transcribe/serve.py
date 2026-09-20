"""Review web server: score + A/B audio + QA table, reachable over the network.

Serves the pipeline output directory. The score (MusicXML) is rendered in the
browser by Verovio (loaded from CDN); audio players expose the original mix,
the separated drums stem, and the sonification for by-ear verification.
"""

from __future__ import annotations

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

INDEX_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>drum-transcribe review</title>
<script src="https://www.verovio.org/javascript/latest/verovio-toolkit-wasm.js" defer></script>
<style>
  body { font-family: system-ui, sans-serif; margin: 1rem 2rem; }
  .players { display: flex; gap: 2rem; flex-wrap: wrap; margin-bottom: 1rem; }
  .players figure { margin: 0; }
  .players figcaption { font-size: .8rem; color: #555; }
  #score svg { max-width: 100%; height: auto; }
  table { border-collapse: collapse; font-size: .8rem; }
  td, th { border: 1px solid #ccc; padding: 2px 8px; text-align: right; }
  tr.sus { background: #ffe0e0; }
  details { margin: 1rem 0; }
</style>
</head>
<body>
<h1>drum-transcribe review</h1>
<div class="players" id="players"></div>
<div id="score">rendering score…</div>
<details><summary>Suspect events (low confidence or large quantization error)</summary>
<table id="qa"><tr><th>bar</th><th>beat</th><th>instrument</th><th>velocity</th>
<th>confidence</th><th>error ms</th></tr></table>
</details>
<script>
const AUDIO = [
  ["original", "original"],
  ["drums stem", "drums"],
  ["sonification (blips = transcription)", "sonification"],
];
for (const [label, route] of AUDIO) {
  const fig = document.createElement("figure");
  fig.innerHTML = `<audio controls preload="none" src="/${route}"></audio>
                   <figcaption>${label}</figcaption>`;
  document.getElementById("players").appendChild(fig);
}

fetch("/files/events.json").then(r => r.json()).then(d => {
  const tbl = document.getElementById("qa");
  for (const e of d.events) {
    if (e.confidence >= 0.5 && Math.abs(e.error_ms) <= 30) continue;
    const tr = document.createElement("tr");
    tr.className = "sus";
    const beat = e.beat[1] === 1 ? e.beat[0] + 1 : `${e.beat[0]}/${e.beat[1]} + 1`;
    tr.innerHTML = `<td>${e.bar}</td><td>${beat}</td><td>${e.instrument}</td>
      <td>${e.velocity}</td><td>${e.confidence}</td><td>${e.error_ms}</td>`;
    tbl.appendChild(tr);
  }
});

document.addEventListener("DOMContentLoaded", () => {
  verovio.module.onRuntimeInitialized = async () => {
    const tk = new verovio.toolkit();
    tk.setOptions({ scale: 35, adjustPageHeight: true, breaks: "smart",
                    pageWidth: 2100, footer: "none" });
    const xml = await fetch("/files/score.musicxml").then(r => r.text());
    tk.loadData(xml);
    let svg = "";
    for (let p = 1; p <= tk.getPageCount(); p++) svg += tk.renderToSVG(p);
    document.getElementById("score").innerHTML = svg;
  };
});
</script>
</body>
</html>
"""


class ReviewHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, outdir: Path, original: Path | None,
                 drums: Path | None, **kwargs):
        self.outdir = outdir
        self.original = original
        self.drums = drums
        super().__init__(*args, directory=str(outdir), **kwargs)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            body = INDEX_HTML.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/original" and self.original:
            self._send_file(self.original)
        elif self.path == "/drums" and self.drums:
            self._send_file(self.drums)
        elif self.path == "/sonification":
            self._send_file(self.outdir / "sonification.wav")
        elif self.path.startswith("/files/"):
            self.path = self.path[len("/files") :]
            super().do_GET()
        else:
            self.send_error(404)

    def _send_file(self, path: Path):
        if not path.exists():
            self.send_error(404, f"{path.name} not found")
            return
        ctype = self.guess_type(str(path))
        with open(path, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def serve(outdir: Path, original: Path | None = None, drums: Path | None = None,
          host: str = "0.0.0.0", port: int = 8765) -> None:
    if drums is None:
        candidates = list(outdir.glob("stems/*/*/drums.wav"))
        drums = candidates[0] if candidates else None
    handler = partial(ReviewHandler, outdir=outdir, original=original, drums=drums)
    httpd = ThreadingHTTPServer((host, port), handler)
    print(f"review UI: http://{host}:{port}/ (serving {outdir})")
    httpd.serve_forever()
