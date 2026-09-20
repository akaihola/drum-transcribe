"""Review web server: compare pipeline variants per song, over the network.

Serves the whole output/ tree. For every song it shows the original, the
separated drums stem, and per-variant sonifications, scores (rendered
in-browser by Verovio) and download links (MusicXML, MuseScore, MIDI, JSON).
"""

from __future__ import annotations

import json
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DOWNLOADS = [
    ("score.mscz", "MuseScore file"),
    ("score.musicxml", "MusicXML"),
    ("audition.mid", "MIDI"),
    ("events.json", "events (JSON)"),
    ("onsets.json", "raw hits (JSON)"),
]

INDEX_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>drum-transcribe review</title>
<script src="https://www.verovio.org/javascript/latest/verovio-toolkit-wasm.js" defer></script>
<style>
  body { font-family: system-ui, sans-serif; margin: 1rem 2rem; }
  h2 { border-bottom: 2px solid #444; padding-bottom: .2rem; margin-top: 2.5rem; }
  .players { display: flex; gap: 2rem; flex-wrap: wrap; margin: .6rem 0; }
  .players figure { margin: 0; }
  .players figcaption { font-size: .8rem; color: #555; }
  .variants { display: flex; gap: 2rem; flex-wrap: wrap; }
  .variant { border: 1px solid #ccc; border-radius: 8px; padding: .8rem 1.2rem; }
  .variant h4 { margin: 0 0 .5rem; }
  .downloads a { margin-right: .8rem; font-size: .85rem; }
  .stats { font-size: .8rem; color: #555; }
  .tabbar { margin-top: 1.2rem; border-bottom: 2px solid #444; }
  .tabbar button { border: 1px solid #999; border-bottom: none; background: #eee;
                   padding: .4rem 1.2rem; cursor: pointer; font-size: 1rem;
                   border-radius: 6px 6px 0 0; margin-right: .3rem; }
  .tabbar button.active { background: #444; color: #fff; }
  .tabpanel { display: none; }
  .tabpanel.active { display: block; }
  .tabpanel svg { max-width: 100%; height: auto; }
  g.measure.now * { fill: #c40000; stroke: #c40000; }
  table { border-collapse: collapse; font-size: .8rem; }
  td, th { border: 1px solid #ccc; padding: 2px 8px; text-align: right; }
  details { margin: .5rem 0; }
</style>
</head>
<body>
<h1>drum-transcribe review</h1>
<p>For each song: listen to the <b>original</b>, the <b>drums stem</b> the
computer isolated, and each pipeline's <b>sonification</b> (the original plus
a synthetic blip for every transcribed hit &mdash; mistakes are easy to hear).
Scores for all pipelines are rendered below; download links give the
MuseScore/MusicXML/MIDI files.</p>
<div id="app">loading…</div>
<script>
const DOWNLOADS = __DOWNLOADS__;

function player(label, url) {
  return `<figure><audio controls preload="none" src="${url}"></audio>
          <figcaption>${label}</figcaption></figure>`;
}

async function build() {
  const index = await fetch("/api/index").then(r => r.json());
  const app = document.getElementById("app");
  let html = "";
  for (const song of index.songs) {
    html += `<section data-song="${song.name}">`;
    html += `<h2>${song.name}</h2><div class="players">`;
    html += player("original", song.source);
    if (song.drums) html += player("drums stem (Demucs)", song.drums);
    html += `</div><div class="variants">`;
    for (const v of song.variants) {
      html += `<div class="variant"><h4>${v.name}</h4>`;
      if (v.files["sonification.wav"])
        html += player("sonification", v.files["sonification.wav"]);
      html += `<div class="stats">${v.n_events} hits, ${v.n_suspect} suspect</div>`;
      html += `<div class="downloads">`;
      for (const [file, label] of DOWNLOADS)
        if (v.files[file]) html += `<a href="${v.files[file]}" download>${label}</a>`;
      html += `</div></div>`;
    }
    html += `</div>`;
    const scored = song.variants.filter(v => v.files["score.musicxml"]);
    if (scored.length) {
      html += `<div class="tabs"><div class="tabbar">` + scored.map((v, i) =>
        `<button class="${i ? "" : "active"}" data-target="${song.name}--${v.name}">
         ${v.name}</button>`).join("") + `</div>`;
      html += scored.map((v, i) =>
        `<div class="tabpanel ${i ? "" : "active"}" id="${song.name}--${v.name}">
         <div class="score" data-url="${v.files["score.musicxml"]}">rendering…</div>
         </div>`).join("") + `</div>`;
    }
    html += `</section>`;
  }
  app.innerHTML = html;
  renderScores();
  followPlayback(index.songs);
}

// While any audio of a song plays, highlight the bar being heard in all of
// that song's scores (bar start times come from the beat grid).
async function followPlayback(songs) {
  const barTimes = {};  // song name -> [{t, bar}]
  for (const s of songs) {
    try {
      const grid = await fetch(s.beats).then(r => r.json());
      let bar = 0;
      barTimes[s.name] = grid.times.map((t, i) => {
        if (grid.positions[i] === 1) bar++;
        return { t, bar };
      });
    } catch (e) { /* song still being processed; no grid yet */ }
  }
  document.addEventListener("timeupdate", e => {
    const section = e.target.closest("section[data-song]");
    if (!section || e.target.paused) return;
    const bars = barTimes[section.dataset.song];
    if (!bars) return;
    let bar = 0;
    for (const b of bars) { if (b.t <= e.target.currentTime + 0.05) bar = b.bar; else break; }
    for (const el of section.querySelectorAll("g.measure.now")) el.classList.remove("now");
    if (bar === 0) return;
    for (const score of section.querySelectorAll(".score")) {
      const m = score.querySelector(`g.measure[data-n="${bar}"]`);
      if (m) m.classList.add("now");
    }
  }, true);
}

// Resolve whether the WASM runtime is already up or still loading.
let vrvReady;

async function renderScores() {
  await vrvReady;
  const tk = new verovio.toolkit();
  tk.setOptions({ scale: 35, adjustPageHeight: true, breaks: "smart",
                  pageWidth: 2100, footer: "none",
                  svgAdditionalAttribute: ["measure@n"] });
  for (const el of document.querySelectorAll(".score")) {
    const xml = await fetch(el.dataset.url).then(r => r.text());
    tk.loadData(xml);
    let svg = "";
    for (let p = 1; p <= tk.getPageCount(); p++) svg += tk.renderToSVG(p);
    el.innerHTML = svg;
  }
}

document.addEventListener("click", e => {
  if (!e.target.matches(".tabbar button")) return;
  const tabs = e.target.closest(".tabs");
  for (const b of tabs.querySelectorAll(".tabbar button"))
    b.classList.toggle("active", b === e.target);
  for (const p of tabs.querySelectorAll(".tabpanel"))
    p.classList.toggle("active", p.id === e.target.dataset.target);
});

document.addEventListener("DOMContentLoaded", () => {
  vrvReady = new Promise(resolve => {
    if (verovio.module.calledRun) resolve();
    else verovio.module.onRuntimeInitialized = resolve;
  });
  build();
});
</script>
</body>
</html>
"""


def scan_output(root: Path) -> dict:
    """Build the JSON index of songs and variants under the output root."""
    songs = []
    for song_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        if song_dir.name.startswith("."):
            continue
        sources = sorted(song_dir.glob("source.*"))
        if not sources:
            continue
        rel = f"/files/{song_dir.name}"
        drums = sorted(song_dir.glob("stems/htdemucs/*/drums.wav"))
        variants = []
        for vdir in sorted(p for p in song_dir.iterdir() if p.is_dir()):
            events_file = vdir / "events.json"
            if not events_file.exists():
                continue
            events = json.loads(events_file.read_text())["events"]
            suspect = [
                e for e in events
                if e["confidence"] < 0.5 or abs(e["error_ms"]) > 30
            ]
            files = {
                f.name: f"{rel}/{vdir.name}/{f.name}"
                for f in vdir.iterdir()
                if f.is_file()
            }
            variants.append(
                {
                    "name": vdir.name,
                    "files": files,
                    "n_events": len(events),
                    "n_suspect": len(suspect),
                }
            )
        songs.append(
            {
                "name": song_dir.name,
                "source": f"{rel}/{sources[0].name}",
                "beats": f"{rel}/beats.json",
                "drums": f"{rel}/{drums[0].relative_to(song_dir)}" if drums else None,
                "variants": variants,
            }
        )
    return {"songs": songs}


class ReviewHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, root: Path, **kwargs):
        self.root = root
        super().__init__(*args, directory=str(root), **kwargs)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            html = INDEX_HTML.replace("__DOWNLOADS__", json.dumps(DOWNLOADS))
            self._send(html.encode(), "text/html; charset=utf-8")
        elif self.path == "/api/index":
            self._send(
                json.dumps(scan_output(self.root)).encode(), "application/json"
            )
        elif self.path.startswith("/files/"):
            self.path = self.path[len("/files") :]
            super().do_GET()
        else:
            self.send_error(404)

    def _send(self, body: bytes, ctype: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def serve(root: Path, host: str = "0.0.0.0", port: int = 8765) -> None:
    handler = partial(ReviewHandler, root=root)
    httpd = ThreadingHTTPServer((host, port), handler)
    print(f"review UI: http://{host}:{port}/ (serving {root})", flush=True)
    httpd.serve_forever()
