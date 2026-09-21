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
import os
import re
import time
from functools import partial
from http.cookies import SimpleCookie
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import gate
from .beats import BeatGrid, regularize
from .ingest import AUDIO_EXTS, VARIANTS, check_url, start_rerun_job, start_version_job

DOWNLOADS = [
    ("score.mscz", "MuseScore file"),
    ("score.musicxml", "MusicXML"),
    ("audition.mid", "MIDI"),
    ("events.json", "events (JSON)"),
    ("onsets.json", "raw hits (JSON)"),
    ("feedback.json", "feedback (JSON)"),
]
UPLOAD_EXTS = AUDIO_EXTS | {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}

# Visual language: docs/style-guide.md ("ink on a drumhead"; live specimen
# at /style). Teal is reserved for "sound happens here".
FONTS = """
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Alegreya:wght@500;700&family=Alegreya+Sans:ital,wght@0,400;0,500;0,700;1,400&display=swap" rel="stylesheet">
"""

STYLE = """
  :root {
    --paper: #FAF9F6; --ink: #232019; --ink-quiet: #6E675C;
    --teal: #0E7386; --teal-deep: #0A5766; --brass: #A66300;
    --signal: #C40000; --hairline: #E2DDD2; --card: #FFFFFF;
    --serif: "Alegreya", Georgia, serif;
    --sans: "Alegreya Sans", system-ui, sans-serif;
  }
  body { font-family: var(--sans); font-size: 17px; line-height: 1.5;
         background: var(--paper); color: var(--ink); margin: 1rem 2rem; }
  h1, h2, h3, h4 { font-family: var(--serif); font-weight: 500; line-height: 1.15; }
  h2 { border-top: 1px solid var(--hairline); padding-top: 1.2rem; margin-top: 1.8rem; }
  a { color: var(--teal-deep); }
  body > p, dialog#help p { max-width: 65ch; }
  summary { cursor: pointer; }
  :focus-visible { outline: 3px solid var(--teal); outline-offset: 2px; }
  .player { margin: 0; background: var(--card); border-radius: 8px;
            border: 1px solid var(--hairline); border-left: 4px solid var(--teal);
            padding: .6rem .8rem .7rem; }
  .player figcaption, .sonihead { font-size: .85rem; color: var(--ink-quiet);
                                  margin-bottom: .4rem; }
  .player figcaption b, .sonihead b { color: var(--ink); font-size: 1rem; }
  .player audio { display: block; width: 16rem; }
  .player audio::-webkit-media-controls-enclosure { background: var(--paper);
                                                    border-radius: 999px; }
  .ic { width: 1.25em; height: 1.25em; vertical-align: -.3em; margin-right: .25em; }
  .grouplbl { display: block; font-weight: 500; color: var(--ink-quiet);
              margin: 1.4rem 0 .4rem; }
  .flow { position: relative; display: grid; margin: .8rem 0 0;
          grid-template-columns: max-content minmax(0, max-content);
          gap: 1rem 5.5rem; align-items: center; }
  .srcs { display: flex; flex-direction: column; gap: 3.2rem; }
  svg.arrows { position: absolute; inset: 0; overflow: visible;
               pointer-events: none; color: var(--ink-quiet); }
  .sonis { display: flex; flex-direction: column; gap: .8rem; }
  .sonis > .grouplbl { margin: 0; }
  .soni { min-width: 26rem; }
  .soni .dimmable { display: flex; align-items: center; gap: .3rem 1rem; flex-wrap: wrap; }
  .soni audio { flex: 1 1 15rem; width: auto; min-width: 15rem; }
  .sonihead { display: flex; gap: .8rem; align-items: baseline; margin-bottom: .35rem; }
  .waiting .dimmable { opacity: .4; pointer-events: none; }
  .spin { display: inline-block; width: .95em; height: .95em; vertical-align: -.12em;
          border: 2px solid var(--hairline); border-top-color: var(--brass);
          border-radius: 50%; animation: spin 1.1s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
  @media (prefers-reduced-motion: reduce) { .spin { animation-duration: 4s; } }
  .docs { display: flex; gap: .7rem; flex-wrap: wrap; }
  a.doc { width: 3.9rem; text-align: center; font-size: .68rem; line-height: 1.25;
          color: var(--ink-quiet); text-decoration: none; word-break: break-all; }
  a.doc svg { width: 1.9rem; height: 2.4rem; display: block; margin: 0 auto .15rem; }
  a.doc:hover { color: var(--teal-deep); }
  .stats { font-size: .85rem; color: var(--ink-quiet); max-width: 75ch; }
  .pending { color: var(--brass); font-style: italic; }
  .error { color: var(--signal); }
  .tabbar { display: flex; flex-wrap: wrap; gap: .4rem; margin: 1.2rem 0 .8rem; }
  .tabbar button { font: inherit; background: none; color: var(--ink);
                   border: 1.5px solid var(--hairline); border-radius: 999px;
                   padding: .4rem 1.2rem; cursor: pointer; }
  .tabbar button:hover { border-color: var(--ink-quiet); }
  .tabbar button.active { background: var(--ink); border-color: var(--ink); color: var(--paper); }
  .tabbar button.add { border-style: dashed; color: var(--ink-quiet); }
  .tabbar button.add.active { border-style: solid; color: var(--paper); }
  .vtabs > .tabpanel.active { border: 1px solid var(--hairline); border-radius: 12px;
                              background: rgba(255,255,255,.55);
                              padding: 1rem 1.4rem 1.4rem; }
  .seg { gap: 0; margin: 0; }
  .seg button { border-radius: 0; margin-left: -1.5px; }
  .seg button:first-child { border-radius: 999px 0 0 999px; margin-left: 0; }
  .seg button:last-child { border-radius: 0 999px 999px 0; }
  .tabpanel { display: none; }
  .tabpanel.active { display: block; }
  .tabpanel svg { max-width: 100%; height: auto; }
  .score { background: var(--card); border: 1px solid var(--hairline);
           border-radius: 8px; padding: .5rem; }
  g.measure.now * { fill: var(--teal); stroke: var(--teal); }
  .score svg { cursor: pointer; }
  form.create { border: 1px solid var(--hairline); background: var(--card);
                border-radius: 8px; padding: 1rem 1.5rem; max-width: 34rem; margin: 1rem 0; }
  form.create label { display: block; margin: .8rem 0 .25rem; font-size: .9rem; }
  form.create input[type=text] { font: inherit; width: 100%; padding: .45rem .7rem;
    border: 1.5px solid var(--hairline); border-radius: 8px; }
  form.create input[type=text]:focus { border-color: var(--teal); outline: none; }
  form.create button { margin-top: 1rem; font: inherit; font-weight: 500; cursor: pointer;
    background: var(--teal); color: #fff; border: none; border-radius: 999px;
    padding: .45rem 1.4rem; }
  form.create button:hover { background: var(--teal-deep); }
  ul.projects li { margin: .3rem 0; }
  .scorehead { display: flex; align-items: center; gap: 1rem; flex-wrap: wrap;
               margin: 1.6rem 0 1.1rem; }
  .scorehead .grouplbl { margin: 0; }
  .meter { display: flex; align-items: center; gap: .5rem; margin-left: auto; }
  .meter .mopt { padding: .3rem .55rem; }
  .meter .mopt svg { display: block; }
  .meter .mopt:disabled { opacity: .4; cursor: default; }
  .minfo { width: 1.6rem; height: 1.6rem; border-radius: 50%; font: inherit;
           font-size: .85rem; border: 1.5px solid var(--hairline);
           background: none; color: var(--ink-quiet); cursor: pointer; }
  .minfo:hover { border-color: var(--ink-quiet); }
  .minfo.sm { width: 1.3rem; height: 1.3rem; font-size: .7rem; padding: 0;
              margin-left: .15rem; vertical-align: .1em; font-style: italic;
              font-family: var(--serif); }
  .popcard { background: var(--card); border: 1px solid var(--hairline);
             border-radius: 8px; box-shadow: 0 6px 24px rgba(35,32,25,.18);
             padding: .8rem 1rem; font-size: .9rem; max-width: 26rem; }
  .popcard a { display: block; margin: .25rem 0; }
  #gear-btn { position: fixed; top: 1rem; right: 4.2rem; width: 2.4rem; height: 2.4rem;
              border-radius: 50%; border: 1.5px solid var(--hairline);
              background: var(--card); color: var(--ink-quiet); cursor: pointer;
              box-shadow: 0 2px 8px rgba(35,32,25,.12); }
  #gear-btn:hover { border-color: var(--ink-quiet); }
  #gear-btn svg { vertical-align: middle; }
  #gearmenu { position: fixed; inset: 3.9rem 1.2rem auto auto; margin: 0; }
  .score.placeholder { display: flex; gap: .6rem; align-items: center;
                       color: var(--ink-quiet); font-size: .9rem; padding: 1rem; }
  @media (max-width: 64rem) {
    .flow { grid-template-columns: 1fr; gap: 1rem; }
    svg.arrows { display: none; }
    .soni { min-width: 0; }
  }
  #help-btn { position: fixed; top: 1rem; right: 1.2rem; width: 2.4rem;
              height: 2.4rem; border-radius: 50%; border: 1.5px solid var(--hairline);
              background: var(--card); color: var(--ink); font: inherit;
              font-size: 1.2rem; cursor: pointer;
              box-shadow: 0 2px 8px rgba(35,32,25,.12); }
  #help-btn:hover { border-color: var(--ink-quiet); }
  dialog#help { max-width: 32rem; max-height: 80vh; overflow-y: auto;
                color: var(--ink); background: var(--card);
                border: 1px solid var(--hairline); border-radius: 8px;
                padding: 1rem 1.6rem; box-shadow: 0 6px 24px rgba(35,32,25,.18); }
  dialog#help::backdrop { background: rgba(35,32,25,.4); }
  dialog#help .close { float: right; border: none; background: none;
                       font-size: 1.4rem; cursor: pointer; color: var(--ink-quiet); }
  .score g.note, .score g.rest, .score g.pgHead { cursor: pointer; }
  .score g.fb * { fill: var(--brass); stroke: var(--brass); }
  .score g.note:hover *, .score g.rest:hover *,
  .score g.pgHead:hover * { fill: var(--teal-deep); stroke: var(--teal-deep); }
  #fbmenu { position: absolute; z-index: 10; background: var(--card);
            border: 1px solid var(--hairline); border-radius: 8px; padding: .8rem 1rem;
            box-shadow: 0 6px 24px rgba(35,32,25,.18); font-size: .9rem; }
  #fbmenu label { display: block; margin: .15rem 0; }
  #fbmenu textarea { font: inherit; width: 100%; margin-top: .4rem;
                     border: 1.5px solid var(--hairline); border-radius: 8px; }
  #fbmenu .row { margin-top: .6rem; display: flex; gap: .6rem; }
  #fbmenu .row button { font: inherit; cursor: pointer; border-radius: 999px;
                        padding: .25rem .9rem; border: 1.5px solid var(--hairline);
                        background: none; }
  #fbmenu .row button[data-act="save"] { background: var(--teal);
                                         border-color: var(--teal); color: #fff; }
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
  recording. <b>Reload the project page</b> to see new results; anything
  still processing is dimmed, with a small spinner — point at the spinner to
  see which step it is waiting on. (The full technical log is behind the
  gear button, top right.) Ticking <b>process on a rented cloud GPU</b> rents
  a fast machine for the job (all results in ~5&ndash;15 minutes, costs about
  a cent); progress then appears in the pipeline log, and the result files
  show up all at once when it finishes.</p>

  <h3>2. Versions and pipelines</h3>
  <svg viewBox="0 0 340 70" width="340">
    <rect x="5" y="5" width="90" height="24" rx="12" fill="#232019"/>
    <text x="50" y="21" fill="#FAF9F6" text-anchor="middle" font-size="12">backing track</text>
    <rect x="100" y="5" width="90" height="24" rx="12" fill="none" stroke="#E2DDD2" stroke-width="1.5"/>
    <text x="145" y="21" text-anchor="middle" font-size="12">album take</text>
    <rect x="5" y="38" width="330" height="26" rx="4" fill="#fff" stroke="#E2DDD2"/>
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
  <span style="color:#0E7386"><b>highlighted in teal</b></span> in the scores
  of the same version.</p>
  <p>It also works the other way: <b>click an empty spot in any bar</b> (not
  on a note — that records feedback) and the recording plays from that bar.
  It uses whichever player is already playing, or the one you listened to
  last, or the original.</p>

  <p>Above the score, a small two-option switch shows the piece's meter:
  <b>steady</b> (the detected time signature, barlines straightened — the
  default) or <b>changing</b> (keep the detected barlines exactly as heard).
  It can be switched only when the beat detector actually heard bars of
  unequal length; the <b>?</b> next to it explains the details.</p>

  <h3>5. Downloads</h3>
  <p>Each pipeline's result files are the small document icons under its
  sonification — click one to download it, or drag it straight into your
  file manager. <b>MusicXML</b> opens directly in MuseScore (File &rarr;
  Open) and is always available; the <b>MuseScore file</b> appears when
  automatic conversion succeeded. <b>MIDI</b> plays the transcription; the
  JSON files hold the raw detection data.</p>

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
  <label><input type="checkbox" name="gpu">
    Process on a rented cloud GPU (faster, costs ~1 cent)</label>
  <label class="unlock" hidden>Many new pieces were added recently, so a
    password is needed just now — ask the site owner for one. It is
    remembered on this browser.
    <input type="password" name="password" autocomplete="current-password"></label>
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
  const gpu = form.gpu.checked;
  if (!file && !url) { alert("Give a link or choose a file."); return false; }
  try {
    if (form.password.value) {  // throttled earlier: unlock, then proceed
      const u = await fetch("/api/unlock", { method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password: form.password.value }) });
      if (!u.ok) throw new Error("wrong password");
    }
    let resp;
    if (file) {
      status.textContent = "uploading…";
      resp = await fetch(`/api/upload?project=${encodeURIComponent(project)}` +
                         `&version=${encodeURIComponent(version)}` +
                         `&filename=${encodeURIComponent(file.name)}` +
                         (gpu ? "&gpu=1" : ""),
                         { method: "PUT", body: file });
    } else {
      status.textContent = "starting…";
      resp = await fetch("/api/create", { method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ project, version, url, gpu }) });
    }
    const d = await resp.json();
    if (resp.status === 429 && d.throttled) {
      status.textContent = "";
      form.querySelector(".unlock").hidden = false;
      form.password.focus();
      return false;
    }
    if (!resp.ok) throw new Error(d.error || resp.statusText);
    location.href = `/p/${d.project}`;
  } catch (e) { status.textContent = ""; alert("Failed: " + e.message); }
  return false;
}
</script>
"""

MAIN_HTML = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>drum-transcribe</title>__FONTS__<style>__STYLE__</style></head>
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
<title>drum-transcribe</title>__FONTS__<style>__STYLE__</style>
<script src="https://www.verovio.org/javascript/latest/verovio-toolkit-wasm.js" defer></script>
</head>
<body>
__HELP__
<button id="gear-btn" title="Advanced: pipeline logs" popovertarget="gearmenu">
  <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor"
       stroke-width="1.8" stroke-linecap="round"><circle cx="12" cy="12" r="3.4"/>
  <path d="M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3M5.3 5.3l2.2 2.2M16.5 16.5l2.2 2.2M18.7 5.3l-2.2 2.2M7.5 16.5l-2.2 2.2"/></svg>
</button>
<div popover id="gearmenu" class="popcard"></div>
<p><a href="/">&larr; all projects</a></p>
<h1 id="title"></h1>
<div id="app">loading…</div>
<div id="addform" hidden>
__CREATE_FORM__
</div>
<script>
const PROJECT = decodeURIComponent(location.pathname.split("/").pop());
const DOWNLOADS = __DOWNLOADS__;
const VARIANTS = __VARIANTS__;
document.getElementById("title").textContent = PROJECT;

const IC_WAVE = `<svg class="ic" viewBox="0 0 26 24" fill="none" stroke="currentColor"
  stroke-width="2" stroke-linecap="round"><path d="M3 10v4M7 7v10M11 4v16M15 8v8M19 5v14M23 10v4"/></svg>`;
const IC_DRUM = `<svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor"
  stroke-width="1.6" stroke-linecap="round"><path d="M3.5 2.5 11 9M20.5 2.5 13 9"/>
  <ellipse cx="12" cy="12" rx="8.5" ry="3"/>
  <path d="M3.5 12v5.5c0 1.8 3.8 3.2 8.5 3.2s8.5-1.4 8.5-3.2V12"/></svg>`;

const INFO = {
  original: "The recording this version was made from — your upload, or the audio fetched from the link, untouched.",
  drums: "Only the drums, pulled out of the full mix by Demucs, a neural network that separates instruments. All transcription starts from this.",
  sonis: "The original recording with a synthetic blip added at every transcribed hit: low thump = kick, snappy noise = snare, high ticks = hi-hat and cymbals. A missing blip is a missed hit; a blip with nothing under it is a false detection. Each pipeline gets its own sonification so you can compare them by ear.",
  adtof: "A neural network trained to read a full drum mix straight into notes. The most reliable pipeline, and the first to finish.",
  mdx23c: "First splits the drums into six per-drum tracks (kick, snare, toms, hi-hat, ride, crash), then detects hits in each track separately. Can tell ride from crash, but tends to over-detect.",
  fused: "adtof's hits, checked against the six per-drum tracks to tell ride from crash and to judge how hard each hit was — the best of both pipelines.",
};

function infoBtn(vname, key) {
  return `<button class="minfo sm" popovertarget="i--${vname}--${key}"
    title="what is this?">i</button>
    <div popover id="i--${vname}--${key}" class="popcard">${INFO[key]}</div>`;
}

// One source/derived audio node in the flow diagram; dimmed with a spinner
// until its file exists.
function node(cls, icon, label, info, url, spinTitle) {
  return `<figure class="player node ${cls} ${url ? "" : "waiting"}">
    <figcaption>${icon}<b>${label}</b>${info}
      ${url ? "" : `<span class="spin" title="${spinTitle}"></span>`}</figcaption>
    <audio class="dimmable" controls preload="none" ${url ? `src="${url}"` : ""}></audio>
  </figure>`;
}

// Why a pipeline's sonification is not there yet, for spinner tooltips.
function explain(v, name) {
  const done = Object.fromEntries(v.steps);
  if (name === "adtof")
    return "still working: adtof reads the drum mix with a neural network (the first results)";
  if (name === "mdx23c")
    return done["kit split into 6 stems (slow)"]
      ? "still working: mdx23c reads each of the six per-drum tracks"
      : "still working: splitting the drum recording into six per-drum tracks (kick, snare, toms, hi-hat, ride, crash) — the slowest step";
  return "still working: fused combines adtof's hits with the six per-drum tracks (needs both)";
}

function dragFile(e, name, url) {
  e.dataTransfer.setData("DownloadURL",
    `application/octet-stream:${name}:${location.origin}${url}`);
}

// Recognizable marks per file type: MuseScore's four-petal star, the
// MusicXML note-in-brackets, the MIDI 5-pin DIN plug, JSON braces.
const FILE_LOGOS = {
  mscz: `<g fill="currentColor">
    <path d="M16 9.5c1.9 1.9 1.9 4.6 0 6.5-1.9-1.9-1.9-4.6 0-6.5z"/>
    <path d="M22.5 16c-1.9 1.9-4.6 1.9-6.5 0 1.9-1.9 4.6-1.9 6.5 0z"/>
    <path d="M16 22.5c-1.9-1.9-1.9-4.6 0-6.5 1.9 1.9 1.9 4.6 0 6.5z"/>
    <path d="M9.5 16c1.9-1.9 4.6-1.9 6.5 0-1.9 1.9-4.6 1.9-6.5 0z"/></g>`,
  musicxml: `<g fill="none" stroke="currentColor" stroke-width="1.4"
      stroke-linecap="round" stroke-linejoin="round">
    <path d="M10 12l-3.5 4L10 20M22 12l3.5 4L22 20"/>
    <path d="M16.8 18.5V11l2.8 1.6"/></g>
    <ellipse cx="15" cy="18.7" rx="2" ry="1.5" fill="currentColor"/>`,
  mid: `<circle cx="16" cy="16" r="6.8" fill="none" stroke="currentColor" stroke-width="1.4"/>
    <g fill="currentColor"><circle cx="11.6" cy="17.6" r="1.1"/>
    <circle cx="13.4" cy="13.5" r="1.1"/><circle cx="16" cy="12" r="1.1"/>
    <circle cx="18.6" cy="13.5" r="1.1"/><circle cx="20.4" cy="17.6" r="1.1"/></g>`,
  json: `<text x="16" y="20" text-anchor="middle" font-size="10"
    fill="currentColor">{ }</text>`,
};

function docIcon(file, label, url) {
  const ext = file.split(".").pop();
  return `<a class="doc" href="${url}" download
    title="${label} — click to download, or drag into a folder"
    ondragstart="dragFile(event, '${file}', '${url}')">
    <svg viewBox="0 0 32 40"><path d="M2 1h19l9 9v29H2z" fill="var(--card)"
      stroke="currentColor" stroke-width="1.5"/>
      <path d="M21 1v9h9" fill="none" stroke="currentColor" stroke-width="1.5"/>
      ${FILE_LOGOS[ext] || FILE_LOGOS.json}
      <text x="16" y="34" text-anchor="middle" font-size="7.5" font-weight="700"
        fill="currentColor">${ext === "musicxml" ? "XML" : ext.toUpperCase()}</text></svg>
    <span>${file}</span></a>`;
}

function soniRow(v, name) {
  const variant = v.variants.find(x => x.name === name);
  const url = variant && variant.files["sonification.wav"];
  let inner = `<div class="sonihead"><b>${name}</b>${infoBtn(v.name, name)}` +
    (variant ? `<span class="stats">${variant.n_events} hits, ${variant.n_suspect} suspect</span>` : "") +
    (url ? "" : `<span class="spin" title="${explain(v, name)}"></span>`) + `</div>`;
  inner += `<div class="dimmable">
    <audio controls preload="none" ${url ? `src="${url}"` : ""}></audio>`;
  if (variant)
    inner += `<div class="docs">` + DOWNLOADS.map(([file, label]) =>
      variant.files[file] ? docIcon(file, label, variant.files[file]) : "").join("") + `</div>`;
  inner += `</div>`;
  return `<div class="player soni ${url ? "" : "waiting"}" data-name="${name}">${inner}</div>`;
}

// Three miniature bars on a one-line staff; sigs = [[num, den], ...] with
// one entry (steady meter) or one per bar (changing meter).
function meterSvg(sigs) {
  let s = `<svg viewBox="0 0 100 28" width="100" height="28" aria-hidden="true"
    stroke="currentColor" fill="currentColor">
    <line x1="1" y1="14" x2="99" y2="14" stroke-width="1"/>`;
  for (const x of [1, 33, 65, 98])
    s += `<line x1="${x}" y1="4" x2="${x}" y2="24" stroke-width="${x === 98 ? 3 : 1}"/>`;
  sigs.forEach(([n, d], i) => {
    const x = [5, 37, 69][i];
    s += `<text x="${x}" y="13" font-size="11" font-weight="700" stroke="none"
            class="${i === 0 ? "msig-num" : ""}">${n}</text>
          <text x="${x}" y="25" font-size="11" font-weight="700" stroke="none">${d}</text>`;
  });
  return s + `</svg>`;
}

function setMeter(version, raw, btn) {
  if (btn.classList.contains("active") || btn.disabled) return;
  for (const b of btn.closest(".mseg").querySelectorAll(".mopt"))
    b.classList.toggle("active", b === btn);
  setRawBars(version, raw);
}

function meterCtl(v) {
  const tracked = v.steps.find(s => s[0] === "beat grid tracked")[1];
  const toggleable = v.irregular || v.raw_bars;
  return `<div class="meter ${tracked ? "" : "waiting"}" data-version="${v.name}">
    <div class="tabbar seg mseg dimmable">
      <button class="mopt ${v.raw_bars ? "" : "active"}"
        title="Steady meter: barlines straightened to the piece&#39;s usual bar length"
        onclick="setMeter('${v.name}', false, this)">${meterSvg([[4, 4]])}</button>
      <button class="mopt ${v.raw_bars ? "active" : ""}" ${toggleable ? "" : "disabled"}
        title="${toggleable
          ? "Changing meter: keep the detected barlines exactly as heard"
          : "No uneven bars were detected in this piece"}"
        onclick="setMeter('${v.name}', true, this)">${meterSvg([[4, 4], [7, 8], [3, 4]])}</button>
    </div>
    <button class="minfo" popovertarget="mx--${v.name}" title="What is this?">?</button>
    <div popover id="mx--${v.name}" class="popcard">
      If the beat detector hears bars of unequal length, the barlines are
      straightened automatically to the piece&#39;s usual bar length (left
      option, showing the detected time signature). Choose the right option
      only if the piece genuinely changes meter — the detected barlines are
      then kept exactly as heard. Switching recomputes the scores; reload in
      a minute. Bar numbers can shift, which orphans feedback already given.</div>
    ${tracked ? "" : `<span class="spin" title="still working: tracking beats and barlines"></span>`}
  </div>`;
}

// Derivation arrows: original -(Demucs)-> drums stem -> each sonification.
// Drawn as an SVG overlay from live element positions, so it survives any
// wrapping; redrawn on tab switches and resizes (hidden panels have no layout).
function drawArrows(panel) {
  const flow = panel && panel.querySelector(".flow");
  if (!flow || !flow.clientWidth) return;
  flow.querySelector("svg.arrows")?.remove();
  const base = flow.getBoundingClientRect();
  const rel = el => {
    const r = el.getBoundingClientRect();
    return { left: r.left - base.left, right: r.right - base.left,
             top: r.top - base.top, bottom: r.bottom - base.top,
             cx: r.left - base.left + r.width / 2,
             cy: r.top - base.top + r.height / 2 };
  };
  const bend = (a, b) => {
    const dx = (b.left - a.right) / 2;
    return `M ${a.right + 5} ${a.cy} C ${a.right + 5 + dx} ${a.cy},
            ${b.left - 5 - dx} ${b.cy}, ${b.left - 7} ${b.cy}`;
  };
  const s = rel(flow.querySelector(".node-src"));
  const d = rel(flow.querySelector(".node-drums"));
  const arrow = p => `<path d="${p}" fill="none" stroke="currentColor"
                      stroke-width="1.5" marker-end="url(#arr)"/>`;
  const label = (x, y, anchor, t) => `<text x="${x}" y="${y}"
    text-anchor="${anchor}" font-size="12" fill="currentColor">${t}</text>`;
  let inner = `<defs><marker id="arr" viewBox="0 0 8 8" refX="7" refY="4"
    markerWidth="6.5" markerHeight="6.5" orient="auto">
    <path d="M0 0 L8 4 L0 8 z" fill="currentColor"/></marker></defs>`;
  inner += arrow(`M ${s.cx} ${s.bottom + 5} L ${s.cx} ${d.top - 7}`);
  inner += label(s.cx + 9, (s.bottom + d.top) / 2 + 4, "start", "Demucs");
  const MODEL = { adtof: "adtof", mdx23c: "mdx23c", fused: "adtof + mdx23c" };
  for (const row of flow.querySelectorAll(".soni")) {
    const r = rel(row);
    inner += arrow(bend(d, r));
    inner += label(r.left - 12, r.cy - 8, "end", MODEL[row.dataset.name] || "");
  }
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", "arrows");
  svg.innerHTML = inner;
  flow.appendChild(svg);
}
window.addEventListener("resize", () =>
  document.querySelectorAll(".vtabs > .tabpanel.active").forEach(drawArrows));

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
  const versions = project ? project.versions : [];
  let html = `<span class="grouplbl">Versions</span>
    <div class="tabs vtabs"><div class="tabbar">` +
    versions.map((v, i) =>
      `<button class="${i ? "" : "active"}" data-target="v--${v.name}">${v.name}</button>`
    ).join("") +
    `<button class="add ${versions.length ? "" : "active"}"
      data-target="v--__add">+ add a version</button></div>`;
  for (const [i, v] of versions.entries()) {
    html += `<div class="tabpanel ${i ? "" : "active"}" id="v--${v.name}">
             <section data-song="${v.name}">`;
    if (v.error)
      html += `<p class="error">Processing failed — the pipeline log
        (gear button, top right) tells what went wrong.</p>`;
    html += `<div class="flow"><div class="srcs">` +
      node("node-src", IC_WAVE, "original", infoBtn(v.name, "original"), v.source,
           "still working: fetching the recording") +
      node("node-drums", IC_DRUM, "drums stem", infoBtn(v.name, "drums"), v.drums,
           "still working: Demucs is isolating the drums from the rest of the band") +
      `</div><div class="sonis"><span class="grouplbl">Sonifications${infoBtn(v.name, "sonis")}</span>` +
      VARIANTS.map(name => soniRow(v, name)).join("") + `</div></div>`;
    const scored = VARIANTS.map(n => v.variants.find(x => x.name === n))
      .filter(x => x && x.files["score.musicxml"]);
    html += `<div class="tabs stabs"><div class="scorehead">
             <span class="grouplbl">Score</span>`;
    if (scored.length)
      html += `<div class="tabbar seg">` + scored.map((x, j) =>
        `<button class="${j ? "" : "active"}" data-target="s--${v.name}--${x.name}">${x.name}</button>`
      ).join("") + `</div>`;
    html += meterCtl(v) + `</div>`;
    if (scored.length)
      html += scored.map((x, j) =>
        `<div class="tabpanel ${j ? "" : "active"}" id="s--${v.name}--${x.name}">
         <div class="score" data-url="${x.files["score.musicxml"]}">rendering…</div></div>`
      ).join("");
    else
      html += `<div class="score placeholder waiting">
        <span class="spin" title="${explain(v, "adtof")}"></span>
        <span class="dimmable">The score appears here when the first pipeline finishes.</span></div>`;
    html += `</div></section></div>`;
  }
  html += `<div class="tabpanel ${versions.length ? "" : "active"}" id="v--__add"></div></div>`;
  app.innerHTML = html;
  const addform = document.getElementById("addform");
  document.getElementById("v--__add").appendChild(addform);
  addform.hidden = false;
  document.getElementById("gearmenu").innerHTML =
    versions.filter(v => v.log).map(v =>
      `<a href="${v.log}">pipeline log — ${v.name}</a>`).join("") ||
    "No pipeline logs yet.";
  renderScores();
  followPlayback(versions);
  requestAnimationFrame(() =>
    drawArrows(document.querySelector(".vtabs > .tabpanel.active")));
}

async function renderScores() {
  await vrvReady;
  const tk = new verovio.toolkit();
  tk.setOptions({ scale: 35, adjustPageHeight: true, breaks: "smart",
                  pageWidth: 2100, footer: "none",
                  svgAdditionalAttribute: ["measure@n"] });
  for (const el of document.querySelectorAll(".score[data-url]")) {
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
    `<textarea rows="2" placeholder="free text…"></textarea>
     <div class="row"><button data-act="save">Save</button>
     <button data-act="delete">Remove</button>
     <button data-act="cancel">Cancel</button></div>`;
  // Anyone who may write feedback may write "</textarea><img onerror=…>",
  // so the saved text goes in as a value, never as markup.
  menu.querySelector("textarea").value = existing.text;
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
      // Detected time signature: the most common beats-per-bar count,
      // shown as the numerator in the steady-meter option.
      const counts = {};
      let len = 0;
      for (const p of grid.positions) {
        if (p === 1 && len) { counts[len] = (counts[len] || 0) + 1; len = 0; }
        len++;
      }
      const num = Object.entries(counts).sort((a, b) => a[1] - b[1]).pop()?.[0];
      const sig = document.querySelector(`.meter[data-version="${v.name}"] .msig-num`);
      if (num && sig) sig.textContent = num;
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

// The MuseScore plugin POSTs /api/seek {bar}; poll it and apply the state.
// The server owns the play/pause toggle (repeated bar = pause), so every
// open page acts the same way — a page must never decide from its own
// audio state, or two open pages hand playback back and forth.
let seekSeq = null;
setInterval(async () => {
  try {
    const s = await fetch("/api/seek").then(r => r.json());
    if (seekSeq !== null && s.seq !== seekSeq) {
      if (!s.playing)
        document.querySelectorAll("audio").forEach(a => a.pause());
      else {
        const section =
          document.querySelector('.tabpanel.active[id^="v--"] section[data-song]');
        if (section) seekToBar(section, s.bar);
      }
    }
    seekSeq = s.seq;
  } catch (e) { /* server briefly down */ }
}, 1000);

document.addEventListener("click", e => {
  const btn = e.target.closest(".tabbar button");
  if (!btn || !btn.dataset.target) return;  // .mopt buttons have no target
  for (const b of btn.closest(".tabbar").querySelectorAll("button"))
    b.classList.toggle("active", b === btn);
  const tabs = btn.closest(".tabs");
  for (const p of tabs.querySelectorAll(":scope > .tabpanel"))
    p.classList.toggle("active", p.id === btn.dataset.target);
  drawArrows(tabs.querySelector(":scope > .tabpanel.active"));
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
# Play/pause-from-bar state. The server decides the toggle: repeating the
# same bar flips `playing`, a new bar always means play. Pages just apply
# the state — if each open page decided from its own local audio instead,
# two open pages with different states would hand playback back and forth
# on every "pause" press (observed 2026-09-20).
SEEK = {"seq": 0, "bar": 0, "playing": False}


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
            html = html.replace("__FONTS__", FONTS)
            html = html.replace("__STYLE__", STYLE).replace("__HELP__", HELP_HTML).replace(
                "__PROJECT_FIELD__",
                '<label>Name of the piece</label><input type="text" name="project" required>',
            ).replace("__FORM_TITLE__", "Transcribe a new piece")
            self._send(html.encode(), "text/html; charset=utf-8")
        elif path.startswith("/p/"):
            html = PROJECT_HTML.replace("__CREATE_FORM__", CREATE_FORM)
            html = (html.replace("__FONTS__", FONTS)
                    .replace("__STYLE__", STYLE)
                    .replace("__HELP__", HELP_HTML)
                    .replace("__PROJECT_FIELD__", "")
                    .replace("__FORM_TITLE__", "Add a version")
                    .replace("__DOWNLOADS__", json.dumps(DOWNLOADS))
                    .replace("__VARIANTS__", json.dumps(list(VARIANTS))))
            self._send(html.encode(), "text/html; charset=utf-8")
        elif path == "/style":
            guide = Path(__file__).parents[2] / "docs" / "style-guide.html"
            self._send(guide.read_bytes(), "text/html; charset=utf-8")
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
                if (kind := self._gate()) is None:
                    return
                url = check_url(data["url"].strip())
                version_dir = self._new_version_dir(data["project"], data["version"])
                gate.write_marker(version_dir, authorized=kind == "auth")
                start_version_job(version_dir, url=url, gpu=bool(data.get("gpu")))
                self._send_json(200, {"project": version_dir.parent.name})
            elif path == "/api/unlock":
                salt = gate.verify_password(str(data.get("password", "")))
                if salt is None:
                    time.sleep(1)  # with ~72-bit passphrases this is plenty
                    self._send_json(403, {"error": "wrong password"})
                else:
                    self._send_json(200, {"ok": True}, headers={
                        "Set-Cookie": f"{gate.COOKIE}={gate.token_for(salt)}; "
                                      "Path=/; Max-Age=31536000; HttpOnly; "
                                      "Secure; SameSite=Lax"})
            elif path == "/api/feedback":
                self._send_json(200, self._save_feedback(data))
            elif path == "/api/rawbars":
                self._set_raw_bars(data)
                self._send_json(200, {"ok": True})
            elif path == "/api/seek":
                bar = int(data["bar"])
                SEEK.update(seq=SEEK["seq"] + 1, bar=bar,
                            playing=not SEEK["playing"] if bar == SEEK["bar"]
                            else True)
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
        if (kind := self._gate()) is None:
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
        gate.write_marker(version_dir, authorized=kind == "auth")
        upload = version_dir / f"upload{suffix}"
        remaining = int(self.headers.get("Content-Length", 0))
        with open(upload, "wb") as f:
            while remaining > 0:
                chunk = self.rfile.read(min(1 << 20, remaining))
                if not chunk:
                    break
                f.write(chunk)
                remaining -= len(chunk)
        start_version_job(version_dir, upload=upload, gpu=q.get("gpu") == "1")
        self._send_json(200, {"project": version_dir.parent.name})

    def _gate(self) -> str | None:
        """"auth"/"anon" if creation may proceed; None after sending 429."""
        if not gate.enabled():
            return "anon"
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        if gate.COOKIE in cookie and gate.valid_token(cookie[gate.COOKIE].value):
            return "auth"
        if gate.allow_anonymous(self.root):
            return "anon"
        self._send_json(429, {"throttled": True, "error": "password needed"})
        self.close_connection = True  # a PUT body may be left unread
        return None

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

    def _send_json(self, status: int, payload: dict,
                   headers: dict[str, str] | None = None) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)


def serve(root: Path, host: str = "0.0.0.0", port: int = 8765) -> None:
    if gate.enabled() and not os.environ.get("TOKEN_SECRET"):
        raise SystemExit("CREATE_PASSWORDS is set but TOKEN_SECRET is not")
    root.mkdir(parents=True, exist_ok=True)
    handler = partial(AppHandler, root=root)
    httpd = ThreadingHTTPServer((host, port), handler)
    print(f"web app: http://{host}:{port}/ (projects in {root})", flush=True)
    httpd.serve_forever()
