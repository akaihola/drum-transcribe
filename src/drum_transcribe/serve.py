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
from .ingest import (
    AUDIO_EXTS,
    RUNNING,
    VARIANTS,
    check_url,
    start_rerun_job,
    start_version_job,
)
from .progress import version_progress

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
  .player audio { display: block; width: 100%; height: 2rem; }
  /* Chromium: volume lives in the one shared slider (.vol), not per player */
  audio::-webkit-media-controls-mute-button,
  audio::-webkit-media-controls-volume-slider,
  audio::-webkit-media-controls-volume-control-container { display: none; }
  .vol { margin-left: auto; display: flex; align-items: center; gap: .4rem;
         color: var(--ink-quiet); font-size: .9rem; }
  .vol input { accent-color: var(--teal); width: 8rem; }
  /* YouTube's own player, cropped to its compact-layout control strip
     (progress bar on top, play/pause in the middle). */
  yt-audio { display: block; position: relative; overflow: hidden;
             height: 2.6rem; border-radius: 6px; background: #000; }
  yt-audio iframe { position: absolute; top: -.6rem; left: 0; width: 100%;
                    height: 4.4rem; border: 0; }
  /* Before the first play YouTube covers its own play button with a
     share/"watch on YouTube" row at this size; this catches the click. */
  yt-audio button { position: absolute; inset: 0; opacity: 0; cursor: pointer; }
  .player audio::-webkit-media-controls-enclosure { background: var(--paper);
                                                    border-radius: 999px; }
  .ic { width: 1.25em; height: 1.25em; vertical-align: -.3em; margin-right: .25em; }
  .grouplbl { display: block; font-weight: 500; color: var(--ink-quiet);
              margin: 1.4rem 0 .4rem; }
  /* Rows: original → drums stem; adtof, mdx23c; fused centred below both. */
  .flow { position: relative; display: grid; margin: .8rem 0 0;
          grid-template-columns: repeat(4, minmax(0, 1fr));
          gap: 3rem 4rem; align-items: start; }
  .flow > .player { grid-column: span 2; }
  .flow > .soni[data-name="fused"] { grid-column: 2 / span 2; }
  svg.arrows { position: absolute; inset: 0; overflow: visible;
               pointer-events: none; color: var(--ink-quiet); }
  .soniline { display: flex; align-items: center; gap: .6rem; }
  .soniline > :first-child { flex: 1; min-width: 0; }
  .sonihead { display: flex; gap: .8rem; align-items: baseline; margin-bottom: .35rem; }
  .waiting .dimmable { opacity: .4; pointer-events: none; }
  .player.waiting { border-left-color: var(--hairline); }  /* teal = plays */
  /* Progress bar standing in for a player until its file exists: brass
     while working, hatched and still while queued ("dead"), red on error. */
  .prog { position: relative; padding: .3rem 0 .1rem; border-radius: 4px; }
  .progtrack { height: 6px; border-radius: 999px; background: var(--hairline);
               overflow: hidden; }
  .progtrack i { display: block; height: 100%; width: 0; border-radius: inherit;
                 background: var(--brass); transition: width 2s linear; }
  .prog.running .progtrack i, .prog.arriving .progtrack i { animation: sheen 2.4s linear infinite;
    background: linear-gradient(90deg, var(--brass) 40%, #D09540 50%, var(--brass) 60%)
                0 0 / 250% 100%; }
  @keyframes sheen { from { background-position: 100% 0; } to { background-position: -150% 0; } }
  .prog.queued .progtrack { background: repeating-linear-gradient(-45deg,
    var(--hairline) 0 3px, transparent 3px 7px); box-shadow: inset 0 0 0 1px var(--hairline); }
  .prog.failed .progtrack { background: rgba(196,0,0,.25); }
  .prog.finishing .progtrack i { width: 100% !important; transition-duration: .4s; }
  .progcap { display: flex; justify-content: space-between; gap: .8rem;
             margin-top: .3rem; font-size: .8rem; color: var(--ink-quiet); }
  .progcap .act { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .progcap .eta { white-space: nowrap; font-variant-numeric: tabular-nums; }
  .prog.queued .progcap, .prog.absent .progcap { font-style: italic; }
  .prog.failed .progcap { color: var(--signal); }
  .prog:hover::after, .prog:focus-visible::after {
    content: attr(data-tip); position: absolute; left: 0; bottom: calc(100% + .35rem);
    z-index: 5; width: max-content; max-width: 22rem; white-space: pre-line;
    background: var(--ink); color: var(--paper); font-size: .8rem; line-height: 1.4;
    padding: .4rem .65rem; border-radius: 6px; pointer-events: none; }
  .prog.absent:hover::after { content: none; }
  .gpu { display: flex; align-items: center; gap: .9rem; margin: .4rem 0 0;
         padding: .6rem .8rem; background: var(--card); border-radius: 8px;
         border: 1px solid var(--hairline); border-left: 4px solid var(--brass); }
  .gpu[hidden] { display: none; }
  .gpu > b { font-weight: 500; white-space: nowrap; }
  .gpu .prog { flex: 1; }
  .arrived { animation: arrive .7s ease-out; }
  @keyframes arrive { from { opacity: .35; } }
  .mbusy { font-size: .8rem; color: var(--brass); font-style: italic; }
  @media (prefers-reduced-motion: reduce) {
    .prog .progtrack i, .arrived { animation: none; }
    .progtrack i { transition: none; }
  }
  .docs { display: flex; gap: .35rem; }
  a.doc { display: grid; place-items: center; width: 1.7rem; height: 1.7rem;
          border-radius: 6px; font-size: .85rem; font-weight: 700;
          color: var(--ink-quiet); text-decoration: none; }
  a.doc img, a.doc svg { width: 1.35rem; height: 1.35rem; }
  a.doc:hover { background: var(--paper); color: var(--teal-deep); }
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
                              background: #F0EDE5;
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
  .score.placeholder { color: var(--ink-quiet); font-size: .9rem; padding: 1rem; }
  .score.placeholder .prog { max-width: 30rem; margin-top: .5rem; }
  @media (max-width: 64rem) {
    .flow { grid-template-columns: 1fr; gap: 1rem; }
    .flow > .player, .flow > .soni[data-name="fused"] { grid-column: auto; }
    svg.arrows { display: none; }
  }
  #help-btn { position: fixed; top: 1rem; right: 1.2rem; width: 2.4rem;
              height: 2.4rem; border-radius: 50%; border: 1.5px solid var(--hairline);
              background: var(--card); color: var(--ink); font: inherit;
              font-size: 1.2rem; cursor: pointer;
              box-shadow: 0 2px 8px rgba(35,32,25,.12); }
  #help-btn:hover, #gh-link:hover { border-color: var(--ink-quiet); }
  #gh-link { position: fixed; bottom: 1rem; right: 1.2rem; width: 2.4rem;
             height: 2.4rem; border-radius: 50%; border: 1.5px solid var(--hairline);
             background: var(--card); color: var(--ink); display: grid;
             place-items: center; box-shadow: 0 2px 8px rgba(35,32,25,.12); }
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
<a id="gh-link" href="https://github.com/akaihola/drum-transcribe"
   title="Source code on GitHub"><svg viewBox="0 0 16 16" width="20" height="20"
   fill="currentColor"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/></svg></a>
<button id="help-btn" title="Help" onclick="document.getElementById('help').showModal()">?</button>
<dialog id="help">
  <button class="close" onclick="document.getElementById('help').close()">×</button>
  <h2>How to use this site</h2>

  <h3>1. Start a transcription</h3>
  <p>On the front page, name the piece and this version of it, then either
  paste a public link (YouTube, a Google Drive share link, or a direct file
  link) or upload a sound/video file. Processing starts immediately in the
  background and takes from minutes up to ~10&times; the length of the
  recording. The project page updates by itself: until a result is ready,
  its player is replaced by a <b>progress bar</b> saying what is being done
  and roughly how long is left. A hatched, empty bar is waiting its turn.
  Point at a bar for the estimated percentage — it is an estimate from how
  long each step usually takes. (The full technical log is behind the
  gear button, top right.) Ticking <b>process on a rented cloud GPU</b> rents
  a fast machine for the job (all results in ~5&ndash;15 minutes, costs about
  a cent); an extra bar at the top shows the machine starting up, which
  usually takes 2&ndash;5 minutes, and the result files show up all at once
  when it finishes.</p>

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
  <p>Each pipeline's result files are the small icons to the right of its
  sonification player (point at one to see its name) — click one to
  download it, or drag it straight into your file manager. The green
  <b>MusicXML</b> logo opens directly in MuseScore (File &rarr; Open) and is
  always available; the purple <b>MuseScore</b> logo appears when automatic
  conversion succeeded. The round plug is <b>MIDI</b>, which plays the
  transcription; the { } braces are JSON files with the raw detection
  data.</p>

  <h3>6. Giving feedback on the score</h3>
  <p>Point at any note or rest in a score: it turns blue. Click it to record
  what is wrong there (extra note, missing note, wrong rhythm&hellip; or
  free text). Notes with saved feedback are tinted orange; hover to read the
  note, click again to edit or remove it. Clicking the score's title takes
  general feedback about the whole transcription. Feedback is stored with
  the other result files (feedback.json). On the public cloud site, saving
  feedback or switching the meter asks for the site's password once per
  browser.</p>
</dialog>
"""

CREATE_FORM = """
<form class="create" onsubmit="submitCreate(this); return false">
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
by ear. Processing runs in the background and the project page shows its
progress live (a 3-minute song takes a few minutes for the first results,
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
const IC_CLOUD = `<svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor"
  stroke-width="1.6" stroke-linejoin="round"><path d="M7 18.5h10.5a4 4 0 0 0 .6-7.95
  A6 6 0 0 0 6.6 9.3 4.6 4.6 0 0 0 7 18.5z"/></svg>`;

const INFO = {
  original: "The recording this version was made from — your upload, or the audio fetched from the link, untouched. For a YouTube link this is YouTube's own player; point at it to see its controls.",
  drums: "Only the drums, pulled out of the full mix by Demucs, a neural network that separates instruments. All transcription starts from this.",
  sonis: "The original recording with a synthetic blip added at every transcribed hit: low thump = kick, snappy noise = snare, high ticks = hi-hat and cymbals. A missing blip is a missed hit; a blip with nothing under it is a false detection. Each pipeline gets its own sonification so you can compare them by ear.",
  adtof: "A neural network trained to read a full drum mix straight into notes. The most reliable pipeline, and the first to finish.",
  mdx23c: "First splits the drums into six per-drum tracks (kick, snare, toms, hi-hat, ride, crash), then detects hits in each track separately. Can tell ride from crash, but tends to over-detect.",
  fused: "adtof's hits, checked against the six per-drum tracks to tell ride from crash and to judge how hard each hit was — the best of both pipelines.",
};

function infoBtn(vname, key, id = key) {
  return `<button class="minfo sm" popovertarget="i--${vname}--${id}"
    title="what is this?">i</button>
    <div popover id="i--${vname}--${id}" class="popcard">${INFO[key]}</div>`;
}

// Stands in for a player until its file exists; showProgress fills it in
// from the server's estimates (task = src, drums, gpu or a pipeline name).
function progBar(task) {
  return `<div class="prog" data-task="${task}" role="progressbar" tabindex="0"
    aria-valuemin="0" aria-valuemax="100"><div class="progtrack"><i></i></div>
    <div class="progcap"><span class="act"></span><span class="eta"></span></div></div>`;
}

const audioTag = url => url && `<audio controls preload="none" src="${url}"></audio>`;

// One source/derived audio node in the flow diagram; a progress bar until
// its player exists.
function node(task, cls, icon, label, info, player) {
  return `<figure class="player node ${cls} ${player ? "" : "waiting"}" data-piece="${task}">
    <figcaption>${icon}<b>${label}</b>${info}</figcaption>
    ${player || progBar(task)}
  </figure>`;
}

// A version made from a YouTube link plays its original in YouTube's own
// embedded player. This element gives it the <audio> interface the page
// relies on (paused, currentTime, volume, play(), pause(), "play" and
// "timeupdate" events), so bar highlighting, click-a-bar and the MuseScore
// plugin drive it like any other player.
let ytApi;
class YtAudio extends HTMLElement {
  connectedCallback() {
    if (this.firstChild) return;
    ytApi ??= new Promise(resolve => {
      window.onYouTubeIframeAPIReady = resolve;
      document.head.append(Object.assign(document.createElement("script"),
        { src: "https://www.youtube.com/iframe_api" }));
    });
    this.innerHTML = `<div></div><button title="play"></button>`;
    this.lastChild.onclick = () => this.play();
    this.playing = false;
    ytApi.then(() => this.yt = new YT.Player(this.firstChild, {
      videoId: this.getAttribute("video"),
      playerVars: { playsinline: 1, rel: 0 },
      events: {
        onReady: () => {
          this.ready = true;
          this.volume = this.vol ?? 1;
          if (this.start != null) this.yt.seekTo(this.start, true);
          if (this.playing) this.yt.playVideo();
        },
        onStateChange: e => {
          clearInterval(this.timer);
          if (e.data === YT.PlayerState.PLAYING) {
            this.playing = true;
            this.querySelector("button")?.remove();
            this.dispatchEvent(new Event("play"));
            this.timer = setInterval(() => this.dispatchEvent(new Event("timeupdate")), 250);
          } else if (e.data !== YT.PlayerState.BUFFERING) this.playing = false;
        },
      },
    }));
  }
  get paused() { return !this.playing; }
  get readyState() { return 1; }  // seeks before the player is ready are queued
  get currentTime() { return this.ready ? this.yt.getCurrentTime() : this.start ?? 0; }
  set currentTime(t) { if (this.ready) this.yt.seekTo(t, true); else this.start = t; }
  get volume() { return this.vol ?? 1; }
  set volume(v) { this.vol = +v; if (this.ready) this.yt.setVolume(this.vol * 100); }
  play() { this.playing = true; if (this.ready) this.yt.playVideo(); }
  pause() { this.playing = false; if (this.ready) this.yt.pauseVideo(); }
}
customElements.define("yt-audio", YtAudio);
const MEDIA = "audio, yt-audio";

function dragFile(e, name, url) {
  e.dataTransfer.setData("DownloadURL",
    `application/octet-stream:${name}:${location.origin}${url}`);
}

// One small download tile per file: the MuseScore and MusicXML logos, the
// MIDI 5-pin DIN plug, braces for JSON; the tooltip names the file.
const FILE_LOGOS = {
  mscz: `<img src="/static/musescore.svg" alt="">`,
  musicxml: `<img src="/static/musicxml.png" alt="">`,
  mid: `<svg viewBox="0 0 32 32"><circle cx="16" cy="16" r="11" fill="none"
    stroke="currentColor" stroke-width="2"/><g fill="currentColor">
    <circle cx="9.5" cy="18.5" r="1.8"/><circle cx="12" cy="12" r="1.8"/>
    <circle cx="16" cy="9.5" r="1.8"/><circle cx="20" cy="12" r="1.8"/>
    <circle cx="22.5" cy="18.5" r="1.8"/></g></svg>`,
  json: `{ }`,
};

function docIcon(file, label, url) {
  return `<a class="doc" href="${url}" download
    title="${file}: ${label} — click to download, or drag into a folder"
    ondragstart="dragFile(event, '${file}', '${url}')"
    >${FILE_LOGOS[file.split(".").pop()] || FILE_LOGOS.json}</a>`;
}

function soniRow(v, name) {
  const variant = v.variants.find(x => x.name === name);
  const url = variant && variant.files["sonification.wav"];
  let inner = `<div class="sonihead"><b>${name}</b>${infoBtn(v.name, name)}
    <span class="stats">sonification${infoBtn(v.name, "sonis", "sonis-" + name)}` +
    (variant ? ` · ${variant.n_events} hits, ${variant.n_suspect} suspect` : "") +
    `</span></div><div class="soniline">` +
    (audioTag(url) || progBar(name));
  if (variant)
    inner += `<div class="docs dimmable">` + DOWNLOADS.map(([file, label]) =>
      variant.files[file] ? docIcon(file, label, variant.files[file]) : "").join("") + `</div>`;
  inner += `</div>`;
  return `<div class="player soni ${url ? "" : "waiting"}" data-name="${name}"
    data-piece="${name}">${inner}</div>`;
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
  const toggleable = v.irregular || v.raw_bars;
  return `<div class="meter ${v.tracked ? "" : "waiting"}" data-version="${v.name}"
    ${v.tracked ? "" : `title="available once the beats and barlines are found"`}>
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
      then kept exactly as heard. Switching recomputes the scores, which
      takes about a minute; the page updates by itself. Bar numbers can
      shift, which orphans feedback already given.</div>
    <span class="mbusy" hidden>recomputing…</span>
  </div>`;
}

// Derivation arrows: original -(Demucs)-> drums stem -> adtof, mdx23c;
// both of those -> fused. Drawn as an SVG overlay from live element
// positions, so it survives any wrapping; redrawn on tab switches and
// resizes (hidden panels have no layout).
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
  const label = (x, y, anchor, t) => `<text x="${x}" y="${y}"
    text-anchor="${anchor}" font-size="12" fill="currentColor">${t}</text>`;
  // a -> b: sideways if b is right of a, else downwards (straight where the
  // two overlap horizontally, an elbow otherwise); label beside the tip.
  const link = (a, b, t) => {
    let p, mx, my;
    if (b.left >= a.right) {
      p = `M ${a.right + 5} ${a.cy} L ${b.left - 7} ${b.cy}`;
      mx = (a.right + b.left) / 2; my = a.cy - 8;
      return arrow(p) + label(mx, my, "middle", t);
    }
    const lo = Math.max(a.left, b.left), hi = Math.min(a.right, b.right);
    const x1 = lo < hi ? (lo + hi) / 2 : a.cx, x2 = lo < hi ? x1 : b.cx;
    const y1 = a.bottom + 5, y2 = b.top - 7;
    my = (y1 + y2) / 2;
    const r = Math.min(8, Math.abs(x2 - x1) / 2), s = Math.sign(x2 - x1);
    p = `M ${x1} ${y1} V ${my - r} Q ${x1} ${my} ${x1 + s * r} ${my}
         H ${x2 - s * r} Q ${x2} ${my} ${x2} ${my + r} V ${y2}`;
    return arrow(p) + label(x2 + 8, (my + y2) / 2 + 5, "start", t);
  };
  const arrow = p => `<path d="${p}" fill="none" stroke="currentColor"
                      stroke-width="1.5" marker-end="url(#arr)"/>`;
  const at = sel => rel(flow.querySelector(sel));
  const src = at(".node-src"), drums = at(".node-drums"),
        adtof = at('[data-name="adtof"]'), mdx = at('[data-name="mdx23c"]'),
        fused = at('[data-name="fused"]');
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", "arrows");
  svg.innerHTML = `<defs><marker id="arr" viewBox="0 0 8 8" refX="7" refY="4"
    markerWidth="6.5" markerHeight="6.5" orient="auto">
    <path d="M0 0 L8 4 L0 8 z" fill="currentColor"/></marker></defs>` +
    link(src, drums, "Demucs") + link(drums, adtof, "ADTOF") +
    link(drums, mdx, "MDX23C") + link(adtof, fused, "hits") +
    link(mdx, fused, "6 drum tracks");
  flow.appendChild(svg);
}
// Show a version tab's contents: arrows, and the players' durations (fetched
// only for the visible version, to spare bandwidth).
function showPanel(panel) {
  drawArrows(panel);
  panel?.querySelectorAll("audio").forEach(a => a.preload = "metadata");
}
window.addEventListener("resize", () =>
  document.querySelectorAll(".vtabs > .tabpanel.active").forEach(drawArrows));

let vrvReady;

// Changing existing results needs the unlock password where the server is
// throttled (the public site). Ask for it when refused, then retry — the
// cookie /api/unlock sets lasts a year, so this happens once per browser.
async function postGated(url, body) {
  const send = () => fetch(url, { method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body) });
  const r = await send();
  if (r.status !== 403) return r;
  const password = prompt("Changing this needs a password — ask the site " +
                          "owner for one. It is remembered on this browser.");
  if (!password) return r;
  const u = await fetch("/api/unlock", { method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ password }) });
  if (!u.ok) { alert("Wrong password."); return r; }
  return send();
}

async function setRawBars(version, raw) {
  const r = await postGated("/api/rawbars", { project: PROJECT, version, raw });
  if (r.ok) pollProgress();
  else alert("Changing the setting failed.");
}

// A version's panel as separately replaceable pieces (each root element
// carries data-piece), so a result that becomes ready swaps in on its own
// without touching players that are playing.
function versionPieces(v) {
  const pieces = {
    err: `<p class="error" data-piece="err" ${v.error ? "" : "hidden"}>Processing
      failed — the pipeline log (gear button, top right) tells what went wrong.</p>`,
    src: node("src", "node-src", IC_WAVE, "original", infoBtn(v.name, "original"),
              v.youtube ? `<yt-audio video="${v.youtube}"></yt-audio>` : audioTag(v.source)),
    drums: node("drums", "node-drums", IC_DRUM, "drums stem", infoBtn(v.name, "drums"),
                audioTag(v.drums)),
  };
  for (const name of VARIANTS) pieces[name] = soniRow(v, name);
  const scored = VARIANTS.map(n => v.variants.find(x => x.name === n))
    .filter(x => x && x.files["score.musicxml"]);
  let score = `<div class="tabs stabs" data-piece="score"><div class="scorehead">
           <span class="grouplbl">Score</span>`;
  if (scored.length)
    score += `<div class="tabbar seg">` + scored.map((x, j) =>
      `<button class="${j ? "" : "active"}" data-target="s--${v.name}--${x.name}">${x.name}</button>`
    ).join("") + `</div>`;
  score += meterCtl(v) + `</div>`;
  if (scored.length)
    score += scored.map((x, j) =>
      `<div class="tabpanel ${j ? "" : "active"}" id="s--${v.name}--${x.name}">
       <div class="score" data-url="${x.files["score.musicxml"]}">rendering…</div></div>`
    ).join("");
  else
    score += `<div class="score placeholder">The score appears here when adtof
      finishes.${progBar("adtof")}</div>`;
  pieces.score = score + `</div>`;
  return pieces;
}

const rendered = {};  // version name -> piece key -> html last put on the page

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
      data-target="v--__add">+ add a version</button>
      <label class="vol" title="volume of all players">volume
        <input type="range" min="0" max="1" step="0.01"
          value="${localStorage.volume ?? 1}" oninput="setVolume(this.value)"></label></div>`;
  for (const [i, v] of versions.entries()) {
    const p = rendered[v.name] = versionPieces(v);
    html += `<div class="tabpanel ${i ? "" : "active"}" id="v--${v.name}">
      <section data-song="${v.name}">${p.err}
      <div class="gpu" hidden>${IC_CLOUD}<b>cloud GPU</b>${progBar("gpu")}</div>
      <div class="flow">${p.src}${p.drums}` + VARIANTS.map(n => p[n]).join("") +
      `</div>${p.score}</section></div>`;
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
  setVolume(localStorage.volume ?? 1);
  renderScores(app);
  for (const v of versions) {
    loadBars(v);
    showProgress(v.name, v.progress);
    progSigs[v.name] = v.progress.sig;
  }
  if (versions.some(v => v.progress.job === "running")) pollProgress();
  requestAnimationFrame(() =>
    showPanel(document.querySelector(".vtabs > .tabpanel.active")));
}

// ---- live progress ------------------------------------------------------
// The server estimates each missing result's progress from the pipeline
// log (progress.py); the page polls it while a job runs and the page is
// visible, and swaps in each result the moment its file appears.
const progSigs = {};  // version name -> server's "something changed" token
let progPolling = false;

function minutes(s) {
  if (s < 50) return "under a minute";
  if (s < 5400) return `about ${Math.max(1, Math.round(s / 60))} min`;
  return `about ${Math.floor(s / 3600)} h ${Math.round(s % 3600 / 60)} min`;
}

function showProgress(vname, prog) {
  const panel = document.getElementById(`v--${vname}`);
  if (!panel) return;
  panel.querySelector(".gpu").hidden = !prog.tasks.gpu;
  // a re-run after a meter switch: the old scores stay up meanwhile
  panel.querySelector(".mbusy").hidden =
    prog.job !== "running" || !panel.querySelector(".score[data-url]");
  for (const el of panel.querySelectorAll(".prog")) {
    const t = prog.tasks[el.dataset.task] ||
      { state: "absent", pct: 0, eta: null, activity: "" };
    let act = t.activity, eta = "", head = `about ${t.pct} % done (an estimate)`;
    if (t.state === "running" && t.eta !== null) eta = `${minutes(t.eta)} left`;
    if (t.state === "queued") {
      head = "not started yet";
      if (t.eta !== null) eta = `ready in ${minutes(t.eta)}`;
    }
    if (t.state === "arriving") head = "100 % done";
    if (t.state === "failed")
      act = "Stopped by an error — the pipeline log (gear button) says why";
    if (t.state === "stopped")
      act = "Interrupted: the server restarted before this was finished";
    if (t.state === "absent") act = "Not made for this version";
    if (!["running", "queued", "arriving"].includes(t.state)) head = "";
    el.className = `prog ${t.state}`;
    el.querySelector("i").style.width = `${t.pct}%`;
    el.querySelector(".act").textContent = act;
    el.querySelector(".eta").textContent = eta;
    const tip = [head, act, eta].filter(Boolean).join("\\n");
    el.dataset.tip = tip;
    el.setAttribute("aria-valuenow", t.pct);
    el.setAttribute("aria-valuetext", tip.replaceAll("\\n", ". "));
  }
}

async function pollProgress() {
  if (progPolling) return;
  progPolling = true;
  while (document.visibilityState === "visible") {
    let running = true;
    try {
      const all = await fetch(`/api/progress?project=${encodeURIComponent(PROJECT)}`)
        .then(r => r.json());
      for (const [name, prog] of Object.entries(all)) {
        if (!(name in progSigs)) continue;  // added elsewhere; shown on reload
        if (prog.sig !== progSigs[name]) {
          progSigs[name] = prog.sig;
          await refreshVersion(name);
        }
        showProgress(name, prog);
      }
      running = Object.values(all).some(p => p.job === "running");
    } catch (e) { /* server briefly down: try again */ }
    if (!running) break;
    await new Promise(r => setTimeout(r, 2000));
  }
  progPolling = false;
}
document.addEventListener("visibilitychange", pollProgress);

// Re-render the pieces of one version whose content changed. A bar about
// to be replaced by its result first runs to the end.
async function refreshVersion(name) {
  const index = await fetch("/api/index").then(r => r.json());
  const v = index.projects.find(p => p.name === PROJECT)
    ?.versions.find(x => x.name === name);
  const panel = document.getElementById(`v--${name}`);
  if (!v || !panel) return;
  for (const [key, html] of Object.entries(versionPieces(v))) {
    const el = panel.querySelector(`[data-piece="${key}"]`);
    if (!el || rendered[name][key] === html ||
        [...el.querySelectorAll(MEDIA)].some(a => !a.paused)) continue;
    const tpl = document.createElement("template");
    tpl.innerHTML = html.trim();
    const fresh = tpl.content.firstElementChild;
    const bars = el.querySelectorAll(".prog");
    if (bars.length && !fresh.querySelector(".prog")) {
      bars.forEach(b => b.classList.add("finishing"));
      await new Promise(r => setTimeout(r, 450));
    }
    const tab = el.querySelector(".tabbar button.active")?.dataset.target;
    el.replaceWith(fresh);
    rendered[name][key] = html;
    if (el.classList.contains("waiting") || bars.length) fresh.classList.add("arrived");
    if (key === "score") {
      fresh.querySelector(`[data-target="${tab}"]`)?.click();
      renderScores(fresh);
    }
  }
  setVolume(localStorage.volume ?? 1);
  showProgress(name, v.progress);
  loadBars(v);
  if (panel.classList.contains("active")) showPanel(panel);
}

// One shared volume for every player, remembered across page loads.
function setVolume(vol) {
  localStorage.volume = vol;
  document.querySelectorAll(MEDIA).forEach(a => a.volume = vol);
}

async function renderScores(root) {
  await vrvReady;
  const tk = new verovio.toolkit();
  tk.setOptions({ scale: 35, adjustPageHeight: true, breaks: "smart",
                  pageWidth: 2100, footer: "none",
                  svgAdditionalAttribute: ["measure@n"] });
  for (const el of root.querySelectorAll(".score[data-url]")) {
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
      const r = await postGated("/api/feedback",
        { project: PROJECT, version, variant, key, labels, text });
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

async function loadBars(v) {
  if (!v.tracked) return;
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
  } catch (e) { /* beat grid being rewritten: next refresh */ }
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

// Seek a version's audio to a bar and play — the player currently playing,
// else the last one used, else the original.
function seekToBar(section, bar) {
  const hit = (barTimes[section.dataset.song] || []).find(b => b.bar === bar);
  const audios = [...section.querySelectorAll(MEDIA)];
  const audio = audios.find(a => !a.paused) ||
                lastAudio[section.dataset.song] || audios[0];
  if (!hit || !audio) return;
  const t = Math.max(0, hit.t - 0.1);
  if (audio.readyState) { audio.currentTime = t; audio.play(); }
  else {  // metadata not loaded yet: it must arrive before seeking works
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
// Poll only while the page is visible or its audio is still playing: a
// forgotten background tab polling once a second keeps the cloud container
// awake for as long as it stays open, and it never scales back to zero.
let seekSeq = null, seekBoot = null, seekPolling = false;
const seekPollWanted = () =>
  document.visibilityState === "visible" ||
  [...document.querySelectorAll(MEDIA)].some(a => !a.paused);

async function pollSeek() {
  if (seekPolling) return;
  seekPolling = true;
  seekSeq = null;  // adopt the current state silently, never replay a seek
  while (seekPollWanted()) {
    try {
      const s = await fetch("/api/seek").then(r => r.json());
      if (s.boot !== seekBoot) seekSeq = null;  // container restarted, reseq
      seekBoot = s.boot;
      if (seekSeq !== null && s.seq !== seekSeq) {
        if (!s.playing)
          document.querySelectorAll(MEDIA).forEach(a => a.pause());
        else {
          const section =
            document.querySelector('.tabpanel.active[id^="v--"] section[data-song]');
          if (section) seekToBar(section, s.bar);
        }
      }
      seekSeq = s.seq;
    } catch (e) { /* server briefly down */ }
    await new Promise(r => setTimeout(r, 1000));
  }
  seekPolling = false;
}
pollSeek();
document.addEventListener("visibilitychange", pollSeek);

document.addEventListener("click", e => {
  const btn = e.target.closest(".tabbar button");
  if (!btn || !btn.dataset.target) return;  // .mopt buttons have no target
  for (const b of btn.closest(".tabbar").querySelectorAll("button"))
    b.classList.toggle("active", b === btn);
  const tabs = btn.closest(".tabs");
  for (const p of tabs.querySelectorAll(":scope > .tabpanel"))
    p.classList.toggle("active", p.id === btn.dataset.target);
  showPanel(tabs.querySelector(":scope > .tabpanel.active"));
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


def youtube_id(version_dir: Path) -> str | None:
    """Video id if the version was made from a YouTube link (source-url.txt)."""
    link = version_dir / "source-url.txt"
    if not link.exists():
        return None
    u = urlparse(link.read_text().strip())
    host = u.hostname or ""
    if host == "youtu.be":
        vid = u.path.strip("/")
    elif host == "youtube.com" or host.endswith(".youtube.com"):
        parts = u.path.strip("/").split("/")
        vid = parts[1] if len(parts) > 1 and parts[0] in ("shorts", "live", "embed") \
            else parse_qs(u.query).get("v", [""])[0]
    else:
        return None
    return vid if re.fullmatch(r"[\w-]{11}", vid) else None


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
            versions.append({
                "name": vdir.name,
                "source": f"{rel}/{sources[0].name}" if sources else None,
                "youtube": youtube_id(vdir),
                "beats": f"{rel}/beats.json",
                "irregular": irregular,
                "raw_bars": (vdir / "keep-raw-bars").exists(),
                "drums": f"{rel}/{drums[0].relative_to(vdir)}" if drums else None,
                "log": f"{rel}/pipeline.log" if log.exists() else None,
                "error": log.exists() and "ERROR:" in log.read_text()[-2000:],
                "tracked": (vdir / "beats.json").exists(),
                "progress": version_progress(vdir, vdir in RUNNING),
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

# Sent alongside SEEK, new on every process start: the cloud container scales
# to zero, so a page can outlive the server it polls and must not read the
# restarted server's seq 0 as a fresh seek back to bar 0.
BOOT = os.urandom(8).hex()


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
        elif re.fullmatch(r"/static/(musescore\.svg|musicxml\.png)", path):
            f = Path(__file__).parent / path[1:]
            self._send(f.read_bytes(), self.guess_type(str(f)))
        elif path == "/style":
            guide = Path(__file__).parents[2] / "docs" / "style-guide.html"
            self._send(guide.read_bytes(), "text/html; charset=utf-8")
        elif path == "/api/index":
            self._send(json.dumps(scan_output(self.root)).encode(), "application/json")
        elif path == "/api/progress":
            project = parse_qs(urlparse(self.path).query).get("project", [""])[0]
            pdir = self.root / project
            if not (re.fullmatch(r"[a-z0-9-]+", project) and pdir.is_dir()):
                self.send_error(404)
                return
            self._send(json.dumps({
                v.name: version_progress(v, v in RUNNING)
                for v in sorted(pdir.iterdir()) if v.is_dir()}).encode(),
                "application/json")
        elif path == "/api/seek":
            self._send(json.dumps(SEEK | {"boot": BOOT}).encode(),
                       "application/json")
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
        if file.is_file() and file.suffix in AUDIO_EXTS and not file.stat().st_size:
            # empty stand-in left by the cloud container's startup sync: the
            # audio stays in the bucket and the browser fetches it from there
            self.send_response(302)
            self.send_header("Location", gate.presigned(
                file.relative_to(self.directory).as_posix()))
            self.end_headers()
            return
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
                (link := version_dir / "source-url.txt").write_text(url + "\n")
                gate.keep(link)
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
                if not self._may_edit():
                    return
                self._send_json(200, self._save_feedback(data))
            elif path == "/api/rawbars":
                if not self._may_edit():
                    return
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

    def _unlocked(self) -> bool:
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        return gate.COOKIE in cookie and gate.valid_token(cookie[gate.COOKIE].value)

    def _may_edit(self) -> bool:
        """May this request change existing results? 403 (and False) if not.

        Feedback and the meter switch write into someone else's results (and
        a re-run costs compute), so where creation is throttled they need the
        unlock password — the anonymous creation budget does not cover them.
        """
        if not gate.enabled() or self._unlocked():
            return True
        self._send_json(403, {"error": "password needed"})
        return False

    def _gate(self) -> str | None:
        """"auth"/"anon" if creation may proceed; None after sending 429."""
        if not gate.enabled():
            return "anon"
        if self._unlocked():
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
