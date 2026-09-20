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

from .beats import BeatGrid, regularize
from .ingest import AUDIO_EXTS, VARIANTS, start_rerun_job, start_version_job

DOWNLOADS = [
    ("score.mscz", "MuseScore file"),
    ("score.musicxml", "MusicXML"),
    ("audition.mid", "MIDI"),
    ("events.json", "events (JSON)"),
    ("onsets.json", "raw hits (JSON)"),
    ("feedback.json", "feedback (JSON)"),
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
  .score svg { cursor: pointer; }
  form.create { border: 1px solid #ccc; border-radius: 8px; padding: 1rem 1.5rem;
                max-width: 34rem; margin: 1rem 0; }
  form.create label { display: block; margin: .6rem 0 .2rem; font-size: .9rem; }
  form.create input[type=text] { width: 100%; padding: .3rem; }
  form.create button { margin-top: 1rem; padding: .4rem 1.4rem; }
  ul.projects li { margin: .3rem 0; }
  ul.progress { list-style: none; padding: .4rem .8rem; margin: .4rem 0;
                border-left: 3px solid #a60; font-size: .85rem; }
  #help-btn { position: fixed; top: 1rem; right: 1.2rem; width: 2.2rem;
              height: 2.2rem; border-radius: 50%; border: 1px solid #888;
              background: #444; color: #fff; font-size: 1.2rem; cursor: pointer; }
  dialog#help { max-width: 30rem; max-height: 80vh; overflow-y: auto;
                border: 1px solid #888; border-radius: 8px; padding: 1rem 1.6rem; }
  dialog#help::backdrop { background: rgba(0,0,0,.4); }
  dialog#help .close { float: right; border: none; background: none;
                       font-size: 1.4rem; cursor: pointer; }
  .score g.note, .score g.rest, .score g.pgHead { cursor: pointer; }
  .score g.fb * { fill: #c8860b; stroke: #c8860b; }
  .score g.note:hover *, .score g.rest:hover *,
  .score g.pgHead:hover * { fill: #0066cc; stroke: #0066cc; }
  #fbmenu { position: absolute; z-index: 10; background: #fff;
            border: 1px solid #888; border-radius: 8px; padding: .8rem 1rem;
            box-shadow: 0 4px 16px rgba(0,0,0,.25); font-size: .9rem; }
  #fbmenu label { display: block; margin: .15rem 0; }
  #fbmenu textarea { width: 100%; margin-top: .4rem; }
  #fbmenu .row { margin-top: .6rem; display: flex; gap: .6rem; }
"""

HELP_HTML = """
<button id="help-btn" title="Help" onclick="document.getElementById('help').showModal()">?</button>
<dialog id="help">
  <button class="close" onclick="document.getElementById('help').close()">×</button>
  <h2>How to use this site</h2>

  <h3>1. Start a transcription</h3>
  <p>On the front page, name the piece and this version of it, then either
  paste a public link (YouTube, a Google Drive share link, or a direct file
  link) or upload a sound/video file. Processing starts immediately in the
  background and takes from minutes up to ~10&times; the length of the
  recording. <b>Reload the project page</b> to see new results; a checklist
  shows what is finished.</p>

  <h3>2. Versions and pipelines</h3>
  <svg viewBox="0 0 340 70" width="340">
    <rect x="5" y="5" width="90" height="24" rx="5" fill="#444"/>
    <text x="50" y="21" fill="#fff" text-anchor="middle" font-size="12">backing track</text>
    <rect x="100" y="5" width="90" height="24" rx="5" fill="#eee" stroke="#999"/>
    <text x="145" y="21" text-anchor="middle" font-size="12">album take</text>
    <rect x="5" y="38" width="330" height="26" rx="4" fill="#fafafa" stroke="#ccc"/>
    <text x="15" y="55" font-size="12">players &middot; downloads &middot; scores of the selected version</text>
  </svg>
  <p>Each <b>version</b> of the piece (e.g. the backing track and the album
  recording) has its own tab. Inside it, independent transcription
  <b>pipelines</b> are compared: <b>adtof</b> (a neural network reading the
  drum mix; most reliable), <b>mdx23c</b> (splits the kit into six
  per-drum tracks first; can tell ride from crash but over-detects), and
  <b>fused</b> (adtof's hits, plus the per-drum tracks to tell ride from
  crash and judge how hard each hit was — the best of both).</p>

  <h3>3. Checking by ear: the sonification</h3>
  <svg viewBox="0 0 340 60" width="340">
    <polyline points="5,30 25,18 45,42 65,25 85,35 105,20 125,40 145,28 165,32 185,22 205,38 225,30"
              fill="none" stroke="#888"/>
    <g fill="#c40000"><circle cx="45" cy="12" r="4"/><circle cx="105" cy="12" r="4"/>
    <circle cx="165" cy="12" r="4"/><circle cx="225" cy="12" r="4"/></g>
    <text x="240" y="16" font-size="11" fill="#c40000">blips = transcribed hits</text>
    <text x="240" y="34" font-size="11" fill="#555">wave = original music</text>
  </svg>
  <p>The <b>sonification</b> is the original recording with a synthetic blip
  added at every transcribed hit (low thump = kick, snappy noise = snare,
  high ticks = hi-hat/cymbals). A missing blip means a missed hit, a blip
  with no drum under it is a false detection, a wrong-sounding blip is the
  wrong drum.</p>

  <h3>4. Following the score</h3>
  <p>While any player is playing, the bar you are hearing is
  <span style="color:#c40000"><b>highlighted in red</b></span> in the scores
  of the same version.</p>
  <p>It also works the other way: <b>click an empty spot in any bar</b> (not
  on a note — that records feedback) and the recording plays from that bar.
  It uses whichever player is already playing, or the one you listened to
  last, or the original.</p>

  <p>If the beat detector hears bars of unequal length, the barlines are
  straightened automatically to the piece's usual bar length, and a checkbox
  appears above the results. Tick it only if the piece genuinely changes
  meter — then the detected barlines are kept as they are.</p>

  <h3>5. Downloads</h3>
  <p><b>MusicXML</b> opens directly in MuseScore (File &rarr; Open) and is
  always available. The ready <b>MuseScore file</b> appears when automatic
  conversion succeeded. <b>MIDI</b> plays the transcription; the JSON files
  hold the raw detection data.</p>

  <h3>6. Giving feedback on the score</h3>
  <p>Point at any note or rest in a score: it turns blue. Click it to record
  what is wrong there (extra note, missing note, wrong rhythm&hellip; or
  free text). Notes with saved feedback are tinted orange; hover to read the
  note, click again to edit or remove it. Clicking the score's title takes
  general feedback about the whole transcription. Feedback is stored with
  the other result files (feedback.json).</p>
</dialog>
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
__HELP__
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
__HELP__
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

async function setRawBars(version, raw) {
  const r = await fetch("/api/rawbars", { method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ project: PROJECT, version, raw }) });
  if (r.ok) alert("Recomputing the scores with this setting — " +
                  "reload the page in a minute to see the result.");
  else alert("Changing the setting failed.");
}

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
    if (v.irregular)
      html += `<p class="stats"><label><input type="checkbox"
        ${v.raw_bars ? "checked" : ""}
        onchange="setRawBars('${v.name}', this.checked)">
        The beat detector heard bars of unequal length here, so the barlines
        were straightened automatically. Tick this only if the piece really
        changes meter (bars of different lengths), to keep the detected
        barlines instead.</label></p>`;
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
    await loadFeedback(el);
  }
}

// ---- score feedback -------------------------------------------------------
// A symbol is addressed as "<bar>:<index of note/rest within the bar>", or
// "title" for the whole transcription; entries live in the variant's
// feedback.json next to the other result files.
const FB_LABELS = ["extra note", "missing note(s)", "wrong rhythm",
                   "wrong drum", "wrong time signature"];
const fbMaps = {};  // panel id -> feedback map

function fbContext(el) {
  const panel = el.closest('.tabpanel[id^="s--"]');
  const [, version, variant] = panel.id.split("--");
  return { panel, version, variant };
}

function symbolKey(sym) {
  if (sym.classList.contains("pgHead")) return "title";
  const measure = sym.closest("g.measure");
  const symbols = [...measure.querySelectorAll("g.note, g.rest")];
  return `${measure.dataset.n}:${symbols.indexOf(sym)}`;
}

function findSymbol(scoreEl, key) {
  if (key === "title") return scoreEl.querySelector("g.pgHead");
  const [bar, idx] = key.split(":");
  const measure = scoreEl.querySelector(`g.measure[data-n="${bar}"]`);
  return measure && [...measure.querySelectorAll("g.note, g.rest")][+idx];
}

async function loadFeedback(scoreEl) {
  const { panel, version, variant } = fbContext(scoreEl);
  const r = await fetch(`/files/${PROJECT}/${version}/${variant}/feedback.json`);
  fbMaps[panel.id] = r.ok ? await r.json() : {};
  annotate(scoreEl);
}

function annotate(scoreEl) {
  const { panel } = fbContext(scoreEl);
  for (const g of scoreEl.querySelectorAll("g.fb")) {
    g.classList.remove("fb");
    g.querySelector(":scope > title")?.remove();
  }
  for (const [key, entry] of Object.entries(fbMaps[panel.id] || {})) {
    const sym = findSymbol(scoreEl, key);
    if (!sym) continue;
    sym.classList.add("fb");
    const tip = document.createElementNS("http://www.w3.org/2000/svg", "title");
    tip.textContent = [...entry.labels, entry.text].filter(Boolean).join("; ");
    sym.prepend(tip);
  }
}

function openFbMenu(sym, x, y) {
  document.getElementById("fbmenu")?.remove();
  const { panel, version, variant } = fbContext(sym);
  const key = symbolKey(sym);
  const existing = (fbMaps[panel.id] || {})[key] || { labels: [], text: "" };
  const menu = document.createElement("div");
  menu.id = "fbmenu";
  menu.innerHTML =
    `<b>${key === "title" ? "Feedback on this transcription" : "Feedback on this symbol"}</b>` +
    FB_LABELS.map(l => `<label><input type="checkbox" value="${l}"
      ${existing.labels.includes(l) ? "checked" : ""}> ${l}</label>`).join("") +
    `<textarea rows="2" placeholder="free text…">${existing.text}</textarea>
     <div class="row"><button data-act="save">Save</button>
     <button data-act="delete">Remove</button>
     <button data-act="cancel">Cancel</button></div>`;
  menu.style.left = `${x}px`;
  menu.style.top = `${y}px`;
  document.body.appendChild(menu);
  menu.addEventListener("click", async e => {
    const act = e.target.dataset?.act;
    if (!act) return;
    if (act !== "cancel") {
      const labels = act === "delete" ? [] :
        [...menu.querySelectorAll("input:checked")].map(i => i.value);
      const text = act === "delete" ? "" : menu.querySelector("textarea").value;
      const r = await fetch("/api/feedback", { method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ project: PROJECT, version, variant, key, labels, text }) });
      if (r.ok) {
        fbMaps[panel.id] = await r.json();
        annotate(panel.querySelector(".score"));
      } else alert("saving feedback failed");
    }
    menu.remove();
  });
}

document.addEventListener("click", e => {
  if (e.target.closest("#fbmenu")) return;
  document.getElementById("fbmenu")?.remove();
  const sym = e.target.closest(".score g.note, .score g.rest, .score g.pgHead");
  if (sym) openFbMenu(sym, e.pageX + 6, e.pageY + 6);
});

// While a version's audio plays, highlight the bar being heard in its scores.
const barTimes = {};   // version name -> [{t, bar}]
const lastAudio = {};  // version name -> the <audio> the user last played

async function followPlayback(versions) {
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
  document.addEventListener("play", e => {
    const section = e.target.closest("section[data-song]");
    if (section) lastAudio[section.dataset.song] = e.target;
  }, true);
}

// Seek a version's audio to a bar and play — the player currently playing,
// else the last one used, else the original.
function seekToBar(section, bar) {
  const hit = (barTimes[section.dataset.song] || []).find(b => b.bar === bar);
  const audios = [...section.querySelectorAll("audio")];
  const audio = audios.find(a => !a.paused) ||
                lastAudio[section.dataset.song] || audios[0];
  if (!hit || !audio) return;
  const t = Math.max(0, hit.t - 0.1);
  if (audio.readyState) { audio.currentTime = t; audio.play(); }
  else {  // preload="none": metadata must arrive before seeking works
    audio.addEventListener("loadedmetadata",
      () => { audio.currentTime = t; }, { once: true });
    audio.play();
  }
}

// Click a bar in a score: play from that bar.
document.addEventListener("click", e => {
  if (document.getElementById("fbmenu")) return;  // click just dismisses menu
  const score = e.target.closest(".score");
  if (!score || e.target.closest("g.note, g.rest, g.pgHead")) return;
  const section = score.closest("section[data-song]");
  for (const m of score.querySelectorAll("g.measure[data-n]")) {
    const r = m.getBoundingClientRect();
    if (e.clientX >= r.left && e.clientX <= r.right &&
        e.clientY >= r.top && e.clientY <= r.bottom)
      return seekToBar(section, +m.dataset.n);
  }
}, true);

// The MuseScore plugin POSTs /api/seek {bar}; poll it and play from that bar
// in the active version tab.
let seekSeq = null;
setInterval(async () => {
  try {
    const s = await fetch("/api/seek").then(r => r.json());
    if (seekSeq !== null && s.seq !== seekSeq) {
      const section =
        document.querySelector('.tabpanel.active[id^="v--"] section[data-song]');
      if (section) seekToBar(section, s.bar);
    }
    seekSeq = s.seq;
  } catch (e) { /* server briefly down */ }
}, 1000);

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
            # Would barline repair change the tracker's raw grid? If yes, the
            # page offers the "uneven bars are real" opt-out checkbox.
            raw_grid = vdir / "beats_raw.json"
            if not raw_grid.exists():
                raw_grid = vdir / "beats.json"
            irregular = False
            if raw_grid.exists():
                g = BeatGrid.load(raw_grid)
                fixed = regularize(g)
                irregular = (fixed.times.tolist() != g.times.tolist()
                             or fixed.positions.tolist() != g.positions.tolist())
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
                "irregular": irregular,
                "raw_bars": (vdir / "keep-raw-bars").exists(),
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


# Latest play-from-bar request (from the MuseScore plugin); pages poll it.
SEEK = {"seq": 0, "bar": 0}


class AppHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, root: Path, **kwargs):
        self.root = root
        super().__init__(*args, directory=str(root), **kwargs)

    def end_headers(self):
        # Pipeline re-runs replace result files in place; force the browser to
        # revalidate (cheap 304s via Last-Modified) so a reload never renders
        # stale artifacts from the heuristic cache.
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            html = MAIN_HTML.replace("__CREATE_FORM__", CREATE_FORM)
            html = html.replace("__STYLE__", STYLE).replace("__HELP__", HELP_HTML).replace(
                "__PROJECT_FIELD__",
                '<label>Name of the piece</label><input type="text" name="project" required>',
            ).replace("__FORM_TITLE__", "Transcribe a new piece")
            self._send(html.encode(), "text/html; charset=utf-8")
        elif path.startswith("/p/"):
            html = PROJECT_HTML.replace("__CREATE_FORM__", CREATE_FORM)
            html = (html.replace("__STYLE__", STYLE)
                    .replace("__HELP__", HELP_HTML)
                    .replace("__PROJECT_FIELD__", "")
                    .replace("__FORM_TITLE__", "Add a version")
                    .replace("__DOWNLOADS__", json.dumps(DOWNLOADS))
                    .replace("__VARIANTS__", json.dumps(list(VARIANTS))))
            self._send(html.encode(), "text/html; charset=utf-8")
        elif path == "/api/index":
            self._send(json.dumps(scan_output(self.root)).encode(), "application/json")
        elif path == "/api/seek":
            self._send(json.dumps(SEEK).encode(), "application/json")
        elif path.startswith("/files/"):
            self.path = self.path[len("/files"):]
            self._send_file()
        else:
            self.send_error(404)

    def _send_file(self) -> None:
        """Static file with byte-range support. Chromium sends `Range: bytes=0-`
        for media and treats the file as unseekable unless it gets a 206 back
        (seeks then snap to 0:00); stdlib SimpleHTTPRequestHandler only ever
        serves whole files, so handle ranges here."""
        rng = re.fullmatch(r"bytes=(\d+)-(\d*)", self.headers.get("Range", ""))
        file = Path(self.translate_path(self.path))
        if not (rng and file.is_file()):
            super().do_GET()
            return
        size = file.stat().st_size
        start = int(rng[1])
        end = min(int(rng[2]) if rng[2] else size - 1, size - 1)
        if start >= size:
            self.send_error(416)
            return
        self.send_response(206)
        self.send_header("Content-Type", self.guess_type(str(file)))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(end - start + 1))
        self.end_headers()
        with file.open("rb") as f:
            f.seek(start)
            remaining = end - start + 1
            while remaining > 0:
                chunk = f.read(min(remaining, 1 << 16))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def do_POST(self):
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", 0))
        try:
            data = json.loads(self.rfile.read(length))
            if path == "/api/create":
                url = data["url"].strip()
                version_dir = self._new_version_dir(data["project"], data["version"])
                start_version_job(version_dir, url=url)
                self._send_json(200, {"project": version_dir.parent.name})
            elif path == "/api/feedback":
                self._send_json(200, self._save_feedback(data))
            elif path == "/api/rawbars":
                self._set_raw_bars(data)
                self._send_json(200, {"ok": True})
            elif path == "/api/seek":
                SEEK.update(seq=SEEK["seq"] + 1, bar=int(data["bar"]))
                self._send_json(200, SEEK)
            else:
                self.send_error(404)
        except (ValueError, KeyError) as e:
            self._send_json(400, {"error": str(e)})

    def _set_raw_bars(self, data: dict) -> None:
        """Flip the keep-raw-bars flag for one version and regenerate results."""
        parts = [data["project"], data["version"]]
        if not all(re.fullmatch(r"[a-z0-9-]+", p) for p in parts):
            raise ValueError("bad path component")
        version_dir = self.root.joinpath(*parts)
        if not version_dir.is_dir():
            raise ValueError("no such version")
        flag = version_dir / "keep-raw-bars"
        if data["raw"]:
            flag.touch()
        else:
            flag.unlink(missing_ok=True)
        start_rerun_job(version_dir)

    def _save_feedback(self, data: dict) -> dict:
        """Set or delete one feedback entry; returns the variant's feedback map."""
        parts = [data["project"], data["version"], data["variant"]]
        if not all(re.fullmatch(r"[a-z0-9-]+", p) for p in parts):
            raise ValueError("bad path component")
        variant_dir = self.root.joinpath(*parts)
        if not variant_dir.is_dir():
            raise ValueError("no such variant")
        fb_file = variant_dir / "feedback.json"
        feedback = json.loads(fb_file.read_text()) if fb_file.exists() else {}
        key = str(data["key"])
        labels = [str(x) for x in data.get("labels", [])]
        text = str(data.get("text", "")).strip()
        if labels or text:
            feedback[key] = {"labels": labels, "text": text}
        else:
            feedback.pop(key, None)
        fb_file.write_text(json.dumps(feedback, indent=1))
        return feedback

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
