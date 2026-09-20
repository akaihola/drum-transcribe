"""Web app: create transcription projects and review/compare the results.

- `/` lists projects and takes a new recording (file upload or public URL —
  YouTube, Google Drive share link, or direct link). Submitting starts the
  pipelines in the background.
- `/p/<project>` shows one project: each uploaded/linked version of the piece
  in its own tab, with audio players, per-pipeline sonifications, download
  links and scores (rendered by Verovio). Reload to see progress.
"""

from __future__ import annotations

import json
import re
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .ingest import AUDIO_EXTS, VARIANTS, start_version_job

DOWNLOADS = [
    ("score.mscz", "MuseScore file"),
    ("score.musicxml", "MusicXML"),
    ("audition.mid", "MIDI"),
    ("events.json", "events (JSON)"),
    ("onsets.json", "raw hits (JSON)"),
]
UPLOAD_EXTS = AUDIO_EXTS | {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}

STYLE = """
  body { font-family: system-ui, sans-serif; margin: 1rem 2rem; }
  h2 { border-bottom: 2px solid #444; padding-bottom: .2rem; margin-top: 2rem; }
  .players { display: flex; gap: 2rem; flex-wrap: wrap; margin: .6rem 0; }
  .players figure { margin: 0; }
  .players figcaption { font-size: .8rem; color: #555; }
  .variants { display: flex; gap: 2rem; flex-wrap: wrap; }
  .variant { border: 1px solid #ccc; border-radius: 8px; padding: .8rem 1.2rem; }
  .variant h4 { margin: 0 0 .5rem; }
  .downloads a { margin-right: .8rem; font-size: .85rem; }
  .stats { font-size: .8rem; color: #555; }
  .pending { color: #a60; font-style: italic; }
  .error { color: #c00; }
  .tabbar { margin-top: 1.2rem; border-bottom: 2px solid #444; }
  .tabbar button { border: 1px solid #999; border-bottom: none; background: #eee;
                   padding: .4rem 1.2rem; cursor: pointer; font-size: 1rem;
                   border-radius: 6px 6px 0 0; margin-right: .3rem; }
  .tabbar button.active { background: #444; color: #fff; }
  .tabpanel { display: none; }
  .tabpanel.active { display: block; }
  .tabpanel svg { max-width: 100%; height: auto; }
  g.measure.now * { fill: #c40000; stroke: #c40000; }
  form.create { border: 1px solid #ccc; border-radius: 8px; padding: 1rem 1.5rem;
                max-width: 34rem; margin: 1rem 0; }
  form.create label { display: block; margin: .6rem 0 .2rem; font-size: .9rem; }
  form.create input[type=text] { width: 100%; padding: .3rem; }
  form.create button { margin-top: 1rem; padding: .4rem 1.4rem; }
  ul.projects li { margin: .3rem 0; }
  ul.progress { list-style: none; padding: .4rem .8rem; margin: .4rem 0;
                border-left: 3px solid #a60; font-size: .85rem; }
"""

CREATE_FORM = """
<form class="create" onsubmit="return submitCreate(this)">
  <b>__FORM_TITLE__</b>
  __PROJECT_FIELD__
  <label>Name of this version (e.g. "backing track", "album recording")</label>
  <input type="text" name="version" required>
  <label>Public link (YouTube, Google Drive share link, or direct URL)</label>
  <input type="text" name="url" placeholder="https://...">
  <label>… or upload a sound/video file</label>
  <input type="file" name="file" accept="audio/*,video/*">
  <button>Start transcription</button>
  <span class="pending" id="create-status"></span>
</form>
<script>
async function submitCreate(form) {
  const status = document.getElementById("create-status");
  const project = form.project ? form.project.value : PROJECT;
  const version = form.version.value;
  const file = form.file.files[0];
  const url = form.url.value.trim();
  if (!file && !url) { alert("Give a link or choose a file."); return false; }
  try {
    let resp;
    if (file) {
      status.textContent = "uploading…";
      resp = await fetch(`/api/upload?project=${encodeURIComponent(project)}` +
                         `&version=${encodeURIComponent(version)}` +
                         `&filename=${encodeURIComponent(file.name)}`,
                         { method: "PUT", body: file });
    } else {
      status.textContent = "starting…";
      resp = await fetch("/api/create", { method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ project, version, url }) });
    }
    const d = await resp.json();
    if (!resp.ok) throw new Error(d.error || resp.statusText);
    location.href = `/p/${d.project}`;
  } catch (e) { status.textContent = ""; alert("Failed: " + e.message); }
  return false;
}
</script>
"""

MAIN_HTML = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>drum-transcribe</title><style>__STYLE__</style></head>
<body>
<h1>drum-transcribe</h1>
<p>Give a recording; get drum sheet music plus everything needed to check it
by ear. Processing runs in the background — reload the project page to watch
results appear (a 3-minute song takes a few minutes for the first results,
tens of minutes for everything).</p>
<h2>Projects</h2>
<ul class="projects" id="projects"><li>loading…</li></ul>
<h2>New piece</h2>
__CREATE_FORM__
<script>
const PROJECT = null;
fetch("/api/index").then(r => r.json()).then(d => {
  const ul = document.getElementById("projects");
  ul.innerHTML = d.projects.map(p =>
    `<li><a href="/p/${p.name}">${p.name}</a> — ` +
    p.versions.map(v => v.name).join(", ") + `</li>`).join("")
    || "<li>none yet</li>";
});
</script>
</body></html>
"""

PROJECT_HTML = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>drum-transcribe</title><style>__STYLE__</style>
<script src="https://www.verovio.org/javascript/latest/verovio-toolkit-wasm.js" defer></script>
</head>
<body>
<p><a href="/">&larr; all projects</a></p>
<h1 id="title"></h1>
<p>Each tab is one version of the piece. Listen to the <b>original</b>, the
<b>drums stem</b>, and each pipeline's <b>sonification</b> (original + a blip
per transcribed hit). While audio plays, the bar being heard is highlighted
in the scores. Reload the page to see processing progress.</p>
<div id="app">loading…</div>
<details><summary>Add another version of this piece for comparison</summary>
__CREATE_FORM__
</details>
<script>
const PROJECT = decodeURIComponent(location.pathname.split("/").pop());
const DOWNLOADS = __DOWNLOADS__;
const VARIANTS = __VARIANTS__;
document.getElementById("title").textContent = PROJECT;

function player(label, url) {
  return `<figure><audio controls preload="none" src="${url}"></audio>
          <figcaption>${label}</figcaption></figure>`;
}

let vrvReady;

async function build() {
  const index = await fetch("/api/index").then(r => r.json());
  const project = index.projects.find(p => p.name === PROJECT);
  const app = document.getElementById("app");
  if (!project) { app.textContent = "project not found"; return; }
  let html = `<div class="tabs vtabs"><div class="tabbar">` +
    project.versions.map((v, i) =>
      `<button class="${i ? "" : "active"}" data-target="v--${v.name}">${v.name}</button>`
    ).join("") + `</div>`;
  for (const [i, v] of project.versions.entries()) {
    html += `<div class="tabpanel ${i ? "" : "active"}" id="v--${v.name}">
             <section data-song="${v.name}">`;
    html += `<div class="players">`;
    if (v.source) html += player("original", v.source);
    if (v.drums) html += player("drums stem (Demucs)", v.drums);
    html += `</div>`;
    if (v.log) html += `<p class="stats"><a href="${v.log}">pipeline log</a>
      ${v.error ? '<span class="error">— processing failed, see log</span>' : ""}
      ${!v.done && !v.error ? '<span class="pending">— still processing, reload for updates</span>' : ""}</p>`;
    if (!v.done && !v.error)
      html += `<ul class="progress">` + v.steps.map(([label, ok]) =>
        `<li>${ok ? "✅" : "⬜"} ${label}</li>`).join("") +
        (v.stage ? `<li class="pending">now: ${v.stage}</li>` : "") + `</ul>`;
    html += `<div class="variants">`;
    for (const name of VARIANTS) {
      const variant = v.variants.find(x => x.name === name);
      html += `<div class="variant"><h4>${name}</h4>`;
      if (variant) {
        if (variant.files["sonification.wav"])
          html += player("sonification", variant.files["sonification.wav"]);
        html += `<div class="stats">${variant.n_events} hits, ${variant.n_suspect} suspect</div>
                 <div class="downloads">`;
        for (const [file, label] of DOWNLOADS)
          if (variant.files[file]) html += `<a href="${variant.files[file]}" download>${label}</a>`;
        html += `</div>`;
      } else {
        html += `<div class="pending">not ready yet</div>`;
      }
      html += `</div>`;
    }
    html += `</div>`;
    const scored = v.variants.filter(x => x.files["score.musicxml"]);
    if (scored.length) {
      html += `<div class="tabs"><div class="tabbar">` + scored.map((x, j) =>
        `<button class="${j ? "" : "active"}" data-target="s--${v.name}--${x.name}">${x.name}</button>`
      ).join("") + `</div>`;
      html += scored.map((x, j) =>
        `<div class="tabpanel ${j ? "" : "active"}" id="s--${v.name}--${x.name}">
         <div class="score" data-url="${x.files["score.musicxml"]}">rendering…</div></div>`
      ).join("") + `</div>`;
    }
    html += `</section></div>`;
  }
  html += `</div>`;
  app.innerHTML = html;
  renderScores();
  followPlayback(project.versions);
}

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

// While a version's audio plays, highlight the bar being heard in its scores.
async function followPlayback(versions) {
  const barTimes = {};
  for (const v of versions) {
    try {
      const grid = await fetch(v.beats).then(r => r.json());
      let bar = 0;
      barTimes[v.name] = grid.times.map((t, i) => {
        if (grid.positions[i] === 1) bar++;
        return { t, bar };
      });
    } catch (e) { /* no beat grid yet */ }
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

document.addEventListener("click", e => {
  if (!e.target.matches(".tabbar button")) return;
  const tabs = e.target.closest(".tabs");
  for (const b of tabs.querySelectorAll(":scope > .tabbar button"))
    b.classList.toggle("active", b === e.target);
  for (const p of tabs.querySelectorAll(":scope > .tabpanel"))
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
</body></html>
"""


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    if not slug:
        raise ValueError("empty name")
    return slug


def scan_output(root: Path) -> dict:
    """Index of projects -> versions -> pipeline variants, from the file tree."""
    projects = []
    for project_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        if project_dir.name.startswith("."):
            continue
        versions = []
        for vdir in sorted(p for p in project_dir.iterdir() if p.is_dir()):
            rel = f"/files/{project_dir.name}/{vdir.name}"
            sources = sorted(vdir.glob("source.*"))
            drums = sorted(vdir.glob("stems/htdemucs/*/drums.wav"))
            log = vdir / "pipeline.log"
            variants = []
            for variant_dir in sorted(p for p in vdir.iterdir() if p.is_dir()):
                events_file = variant_dir / "events.json"
                if not events_file.exists():
                    continue
                events = json.loads(events_file.read_text())["events"]
                suspect = [e for e in events
                           if e["confidence"] < 0.5 or abs(e["error_ms"]) > 30]
                variants.append({
                    "name": variant_dir.name,
                    "files": {f.name: f"{rel}/{variant_dir.name}/{f.name}"
                              for f in variant_dir.iterdir() if f.is_file()},
                    "n_events": len(events),
                    "n_suspect": len(suspect),
                })
            stage = None
            if log.exists():
                markers = [ln for ln in log.read_text().splitlines()
                           if ln.startswith(("==", "ERROR"))]
                stage = markers[-1].strip("= ") if markers else None
            done = {v["name"] for v in variants}
            versions.append({
                "name": vdir.name,
                "source": f"{rel}/{sources[0].name}" if sources else None,
                "beats": f"{rel}/beats.json",
                "drums": f"{rel}/{drums[0].relative_to(vdir)}" if drums else None,
                "log": f"{rel}/pipeline.log" if log.exists() else None,
                "error": log.exists() and "ERROR:" in log.read_text()[-2000:],
                "done": done == set(VARIANTS),
                "stage": stage,
                # ordered progress checklist shown while processing
                "steps": [
                    ["source audio fetched", bool(sources)],
                    ["drums isolated (Demucs)", bool(drums)],
                    ["beat grid tracked", (vdir / "beats.json").exists()],
                    ["adtof transcription", "adtof" in done],
                    ["kit split into 6 stems (slow)",
                     any((vdir / "stems" / "mdx23c").glob("*")) if (vdir / "stems" / "mdx23c").is_dir() else False],
                    ["mdx23c transcription", "mdx23c" in done],
                ],
                "variants": variants,
            })
        if versions:
            projects.append({"name": project_dir.name, "versions": versions})
    return {"projects": projects}


class AppHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, root: Path, **kwargs):
        self.root = root
        super().__init__(*args, directory=str(root), **kwargs)

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            html = MAIN_HTML.replace("__CREATE_FORM__", CREATE_FORM)
            html = html.replace("__STYLE__", STYLE).replace(
                "__PROJECT_FIELD__",
                '<label>Name of the piece</label><input type="text" name="project" required>',
            ).replace("__FORM_TITLE__", "Transcribe a new piece")
            self._send(html.encode(), "text/html; charset=utf-8")
        elif path.startswith("/p/"):
            html = PROJECT_HTML.replace("__CREATE_FORM__", CREATE_FORM)
            html = (html.replace("__STYLE__", STYLE)
                    .replace("__PROJECT_FIELD__", "")
                    .replace("__FORM_TITLE__", "Add a version")
                    .replace("__DOWNLOADS__", json.dumps(DOWNLOADS))
                    .replace("__VARIANTS__", json.dumps(list(VARIANTS))))
            self._send(html.encode(), "text/html; charset=utf-8")
        elif path == "/api/index":
            self._send(json.dumps(scan_output(self.root)).encode(), "application/json")
        elif path.startswith("/files/"):
            self.path = self.path[len("/files"):]
            super().do_GET()
        else:
            self.send_error(404)

    def do_POST(self):
        if urlparse(self.path).path != "/api/create":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", 0))
        try:
            data = json.loads(self.rfile.read(length))
            url = data["url"].strip()
            version_dir = self._new_version_dir(data["project"], data["version"])
        except (ValueError, KeyError) as e:
            self._send_json(400, {"error": str(e)})
            return
        start_version_job(version_dir, url=url)
        self._send_json(200, {"project": version_dir.parent.name})

    def do_PUT(self):
        parsed = urlparse(self.path)
        if parsed.path != "/api/upload":
            self.send_error(404)
            return
        q = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        try:
            suffix = Path(q.get("filename", "")).suffix.lower()
            if suffix not in UPLOAD_EXTS:
                raise ValueError(f"unsupported file type: {suffix or 'none'}")
            version_dir = self._new_version_dir(q["project"], q["version"])
        except (ValueError, KeyError) as e:
            self._send_json(400, {"error": str(e)})
            return
        version_dir.mkdir(parents=True, exist_ok=True)
        upload = version_dir / f"upload{suffix}"
        remaining = int(self.headers.get("Content-Length", 0))
        with open(upload, "wb") as f:
            while remaining > 0:
                chunk = self.rfile.read(min(1 << 20, remaining))
                if not chunk:
                    break
                f.write(chunk)
                remaining -= len(chunk)
        start_version_job(version_dir, upload=upload)
        self._send_json(200, {"project": version_dir.parent.name})

    def _new_version_dir(self, project: str, version: str) -> Path:
        version_dir = self.root / slugify(project) / slugify(version)
        if version_dir.exists():
            raise ValueError(f"version '{version_dir.name}' already exists")
        return version_dir

    def _send(self, body: bytes, ctype: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def serve(root: Path, host: str = "0.0.0.0", port: int = 8765) -> None:
    root.mkdir(parents=True, exist_ok=True)
    handler = partial(AppHandler, root=root)
    httpd = ThreadingHTTPServer((host, port), handler)
    print(f"web app: http://{host}:{port}/ (projects in {root})", flush=True)
    httpd.serve_forever()
