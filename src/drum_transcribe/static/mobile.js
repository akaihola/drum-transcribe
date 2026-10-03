// Phone layout, "drum pads" (phones only; serve.py's head script loads it).
// A version is laid out like a drum machine's pad grid: tap a pad to hear
// that stage of the pipeline, tap another to hear the same moment through
// it. A bottom tab bar switches Listen · Score · Files (· Record), and a mini
// player follows whatever plays. The page's own players stay in the hidden
// .flow; the pads only drive them, so live refresh and the score keep working.

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const html = document.documentElement;
const svg = (body, w = 24) => `<svg class="mi" viewBox="0 0 ${w} 24" aria-hidden="true">${body}</svg>`;
const IC = {
  wave: svg(`<path d="M3 10v4M7 7v10M11 4v16M15 8v8M19 5v14M23 10v4"/>`, 26),
  drum: svg(`<path d="M3.5 2.5 11 9M20.5 2.5 13 9"/><ellipse cx="12" cy="12" rx="8.5" ry="3"/>
    <path d="M3.5 12v5.5c0 1.8 3.8 3.2 8.5 3.2s8.5-1.4 8.5-3.2V12"/>`),
  band: svg(`<path d="M9 18V5.5l11-2.5v13"/><circle cx="6" cy="18" r="3"/><circle cx="17" cy="16" r="3"/>`),
  // the recording's waveform with a blip above some hits: a sonification
  blips: svg(`<path d="M3 14v4M7 11v10M11 15v3M15 10v11M19 14v5M23 15v3"/>
    <circle class="f" cx="7" cy="4.5" r="2"/><circle class="f" cx="15" cy="4.5" r="2"/><circle class="f" cx="23" cy="8" r="2"/>`, 26),
  pads: svg(`<rect x="3.5" y="3.5" width="7" height="7" rx="2"/><rect x="13.5" y="3.5" width="7" height="7" rx="2"/>
    <rect x="3.5" y="13.5" width="7" height="7" rx="2"/><rect x="13.5" y="13.5" width="7" height="7" rx="2"/>`),
  score: svg(`<path d="M2 7h20M2 11.5h20M2 16h20" stroke-width="1.1"/>
    <ellipse class="f" cx="9" cy="17.5" rx="3.3" ry="2.4" transform="rotate(-22 9 17.5)"/><path d="M12 17V3l5 2.5" stroke-width="2"/>`),
  down: svg(`<path d="M12 3.5v11m-4.5-4.5 4.5 4.5 4.5-4.5M4.5 19.5h15"/>`),
  rec: svg(`<circle cx="12" cy="12" r="8.5"/><circle class="f" cx="12" cy="12" r="4"/>`),
  back: svg(`<path d="M15 5 8 12l7 7"/>`),
  log: svg(`<path d="M6 3h8l4 4v14H6zM14 3v4h4M9 12h6M9 16h6"/>`),
  open: svg(`<path d="M14 4h6v6M20 4l-9 9M18 14v5H5V6h5"/>`),
  play: svg(`<path class="f" d="M8 5.5v13l10.5-6.5z"/>`),
  pause: svg(`<path class="f" d="M7 5h3.5v14H7zM13.5 5H17v14h-3.5z"/>`),
  talk: svg(`<path d="M4 5h16v11H10l-4 3.5V16H4z"/><path d="M8 9.5h8M8 12.5h5"/>`),
};

// Pad key (= the page's data-piece) -> [name, icon, INFO key, subtitle when ready]
const PADS = {
  src: ["original", IC.wave, "original", "the full recording"],
  drums: ["drums stem", IC.drum, "drums", "drums only"],
  drumless: ["without drums", IC.band, "drumless", "the band, no drums"],
  adtof: ["adtof", IC.blips, "adtof"],
  mdx23c: ["mdx23c", IC.blips, "mdx23c"],
  fused: ["fused", IC.blips, "fused"],
};
const TAGLINE = { adtof: "the most reliable", mdx23c: "tells ride from crash, over-detects",
                  fused: "the best of both" };
const WAITING = { running: p => p.eta || p.act || "working…",
                  queued: p => p.eta || "waiting its turn", arriving: () => "almost ready",
                  failed: () => "failed — see the log", stopped: () => "interrupted",
                  absent: () => "none in this version" };
const STATES = Object.keys(WAITING);
const TABS = [["listen", "Listen", IC.pads], ["score", "Score", IC.score],
              ["files", "Files", IC.down], ["record", "Record", IC.rec]];
const ZOOM = [30, 35, 40, 45, 52, 60, 70, 80];  // SCORE_SCALE steps
const still = matchMedia("(prefers-reduced-motion: reduce)");
const cur = {};  // version -> key of the pad the mini player controls

const mediaOf = (section, key) => key && $(`[data-piece="${key}"]`, section)?.querySelector(MEDIA);
const keyOf = el => el.closest("[data-piece]")?.dataset.piece;
const duration = el => el.owner?.duration ?? el.yt?.getDuration?.() ?? el.duration;
const clock = t => Number.isFinite(t) ? `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, "0")}` : "–:––";
const activePanel = () => $('.vtabs > .tabpanel.active');
const activeSection = () => $("section[data-song]", activePanel() || document.createElement("i"));

// ---- chrome: header, tab bar, mini player, info sheet -------------------
const head = document.createElement("header");
head.className = "mhead";
head.innerHTML = `<div class="mbar"></div><label class="vpick"><span>Version</span>
  <select aria-label="Version"></select></label>`;
const back = $('body > p > a[href="/"]');
back.parentElement.remove();
back.className = "mback";
back.setAttribute("aria-label", "All projects");
back.innerHTML = IC.back;
$(".mbar", head).append(back, $("#title"), $("#help-btn"), $("#gear-btn"));
$("#app").before(head);
const pick = $("select", head);
pick.onchange = () => {
  $(`.vtabs > .tabbar button[data-target="${pick.value}"]`).click();
  const panel = activePanel();
  // one version at a time: whatever plays elsewhere stops with its tab
  $$(".vtabs > .tabpanel").filter(p => p !== panel)
    .forEach(p => $$(MEDIA, p).forEach(a => a.pause()));
  sync();
};

const bar = document.createElement("nav");
bar.className = "mtabs";
bar.innerHTML = TABS.map(([k, label, ic]) =>
  `<button type="button" data-tab="${k}"><span class="tic">${ic}</span>${label}</button>`).join("");
bar.onclick = e => {
  const tab = e.target.closest("[data-tab]")?.dataset.tab;
  if (!tab || tab === html.dataset.mtab) return;
  scrolls[html.dataset.mtab] = scrollY;
  localStorage.mtab = tab;
  setTab(tab);
  scrollTo(0, scrolls[tab] || 0);
};
const scrolls = {};  // tab -> scroll position, so hopping Score <-> Listen keeps your place

const mini = document.createElement("div");
mini.className = "mplay";
mini.hidden = true;
mini.innerHTML = `<button type="button" class="mp-name"><span class="tic"></span><b></b></button>
  <span class="mp-time"></span><input type="range" min="0" step="0.1" aria-label="Position">
  <button type="button" class="mp-btn"></button>`;
const [miniName, miniTime, miniRange, miniBtn] = [$(".mp-name", mini), $(".mp-time", mini),
  $("input", mini), $(".mp-btn", mini)];
miniName.onclick = () => $('[data-tab="listen"]', bar).click();
miniBtn.onclick = () => {
  const el = mediaOf(activeSection(), cur[activeSection()?.dataset.song]);
  if (el?.paused) quiet(el.play()); else el?.pause();
};
miniRange.oninput = () => {
  const el = mediaOf(activeSection(), cur[activeSection()?.dataset.song]);
  if (el) el.currentTime = +miniRange.value;
};

const sheet = document.createElement("dialog");
sheet.className = "msheet";
document.body.append(bar, mini, sheet);
// bottom sheets: a tap on the dimmed page above closes them
for (const d of [sheet, $("#help")])
  d.addEventListener("click", e => { if (e.clientY < d.getBoundingClientRect().top) d.close(); });
$("#help").prepend(Object.assign(document.createElement("div"), { className: "grab" }));

// play() promises reject when a pause() or a quick second tap cuts them short
const quiet = p => p?.catch?.(() => {});

// ---- the pads -------------------------------------------------------------
function padHtml(key) {
  const [name, ic] = PADS[key];
  return `<div class="pad" data-key="${key}" style="grid-area:${key}">
    <button type="button" class="pad-hit"><span class="pad-ic">${ic}
      <span class="eq"><i></i><i></i><i></i><i></i></span></span><b>${name}</b><span class="pad-sub"></span></button>
    <button type="button" class="pad-i" aria-label="What is ${name}?"><span>i</span></button></div>`;
}

function padState(section, key) {
  const piece = $(`[data-piece="${key}"]`, section);
  const media = piece?.querySelector(MEDIA);
  if (media) return { st: "ready", media };
  const prog = piece?.querySelector(".prog");
  return { st: STATES.find(s => prog?.classList.contains(s)) || "absent",
           pct: parseFloat(prog?.querySelector("i").style.width) || 0,
           eta: $(".eta", prog || piece)?.textContent, act: $(".act", prog || piece)?.textContent,
           tip: prog?.dataset.tip };
}

function readySub(section, key) {
  const stats = $(`[data-piece="${key}"] .stats`, section)?.textContent.match(/(\d+) hits, (\d+) suspect/);
  if (stats) return `${stats[1]} hits · <em>${stats[2]} suspect</em>`;
  return PADS[key][3] || "sonification";
}

// Arrows between the pads, from their live positions (the grid's width
// follows the phone). Straight down where two pads overlap, else diagonal.
function drawPadArrows(grid) {
  if (!grid.offsetWidth) return;
  const g = grid.getBoundingClientRect();
  const box = k => {
    const r = $(`[data-key="${k}"]`, grid).getBoundingClientRect();
    return { l: r.left - g.left, r: r.right - g.left, t: r.top - g.top, b: r.bottom - g.top };
  };
  const [s, d, l, a, m, f] = Object.keys(PADS).map(box);
  const x = (p, q) => (Math.max(p.l, q.l) + Math.min(p.r, q.r)) / 2;
  const mid = (p, q) => (p.b + q.t) / 2 + 4.5;
  const down = (p, q) => `<path d="M${x(p, q)} ${p.b + 5}V${q.t - 6}"/>`;
  const text = (tx, ty, anchor, t) => `<text x="${tx}" y="${ty}" text-anchor="${anchor}">${t}</text>`;
  // drums stem forks: straight down to adtof, an elbow across to mdx23c
  const xd = x(d, a), xm = (m.l + m.r) / 2, ym = (d.b + m.t) / 2, r = 8;
  grid.querySelector("svg.parrows")?.remove();
  grid.insertAdjacentHTML("beforeend", `<svg class="parrows" aria-hidden="true">
    <defs><marker id="pa" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7"
      orient="auto"><path d="M0 0 L8 4 L0 8 z"/></marker></defs>
    <g class="lines">${down(s, d)}${down(s, l)}${down(d, a)}
      <path d="M${xd} ${d.b + 5}V${ym - r}Q${xd} ${ym} ${xd + r} ${ym}H${xm - r}Q${xm} ${ym} ${xm} ${ym + r}V${m.t - 6}"/>${down(a, f)}${down(m, f)}</g>
    ${text((x(s, d) + x(s, l)) / 2, mid(s, d), "middle", "Demucs")}
    ${text(x(d, a) - 9, mid(d, a), "end", "ADTOF")}
    ${text((xd + xm) / 2, ym - 7, "middle", "MDX23C")}
    ${text(x(a, f) - 9, mid(a, f), "end", "hits")}
    ${text(x(m, f) + 9, mid(m, f), "start", "6 drum tracks")}</svg>`);
}

function tapPad(section, key) {
  const v = section.dataset.song, el = mediaOf(section, key);
  if (!el) return openInfo(section, key);
  if (!el.paused) return el.pause();
  const from = mediaOf(section, cur[v]);
  cur[v] = key;
  lastAudio[v] = el;  // a tap on the score then plays this pad too
  // secure mode: one shared transport, so choosing the backing keeps the position
  if (el.tagName === "PRACTICE-AUDIO") return quiet(el.play());
  const t = from ? from.currentTime : 0;
  $$(MEDIA, section).forEach(a => a !== el && a.pause());
  if (from && from !== el) {
    if (el.readyState) el.currentTime = t;
    else el.addEventListener("loadedmetadata", () => { el.currentTime = t; }, { once: true });
  }
  quiet(el.play());
}

function openInfo(section, key) {
  const [name, , info] = PADS[key], p = padState(section, key), pipeline = !PADS[key][3];
  const status = p.st === "ready" ? "" : `<p class="sh-status ${p.st}">${
    (p.tip || WAITING[p.st](p)).split("\n").join("<br>")}</p>`;
  sheet.innerHTML = `<div class="grab"></div><h3>${name}</h3>${status}<p>${INFO[info]}</p>` +
    (pipeline ? `<h4>What the pad plays</h4><p>${INFO.sonis}</p>` : "") +
    `<button type="button" class="sh-close" onclick="this.closest('dialog').close()">Close</button>`;
  sheet.showModal();
}

document.addEventListener("click", e => {
  const pad = e.target.closest(".pad");
  if (pad) {
    const section = pad.closest("section[data-song]");
    if (e.target.closest(".pad-i")) openInfo(section, pad.dataset.key);
    else tapPad(section, pad.dataset.key);
  }
  const z = e.target.closest("[data-zoom]");
  if (z) zoom(+z.dataset.zoom);
});

// ---- files ----------------------------------------------------------------
function filesHtml(section) {
  const v = section.dataset.song;
  const row = (href, logo, name, file, attrs = "download", note = "") =>
    `<a class="frow" href="${href}" ${attrs}><span class="flogo">${logo}</span>
     <span class="fname"><b>${name}</b><small>${file}</small>${note}</span>${
       attrs === "download" ? IC.down : IC.open}</a>`;
  const group = (title, tag, rows, empty) => `<h3>${title}${tag ? ` <small>${tag}</small>` : ""}</h3>
    ${rows ? `<div class="fgroup">${rows}</div>` : `<p class="fempty">${empty}</p>`}`;
  const drumless = $('[data-piece="drumless"] a.download', section);
  let out = group("Without drums", "play along on your kit", drumless &&
    row(drumless.getAttribute("href"), IC.band, "Without drums", drumless.getAttribute("download")),
    "Appears when Demucs has separated the drums.");
  for (const name of Object.keys(PADS).slice(3)) {
    const docs = $$(`[data-piece="${name}"] a.doc`, section);
    const rows = DOWNLOADS.map(([file, label]) => {
      const a = docs.find(d => d.getAttribute("href").endsWith(`/${file}`));
      return a ? row(a.getAttribute("href"), a.innerHTML, label, file, "download",
        a.classList.contains("warn") ? `<small class="warn">MuseScore found problems; some bars may look wrong</small>` : "") : "";
    }).join("");
    const st = padState(section, name).st;
    out += group(name, TAGLINE[name], rows, st === "absent" || st === "ready"
      ? "Not made for this version." : `Appears when ${name} finishes.`);
  }
  const log = $(`#gearmenu a[href$="/${v}/pipeline.log"]`);
  return out + group("Pipeline log", "every step, for troubleshooting", log &&
    row(log.getAttribute("href"), IC.log, "Pipeline log", "pipeline.log", 'target="_blank"'),
    "No log for this version.");
}

// ---- score ----------------------------------------------------------------
function zoom(step) {
  const i = ZOOM.findIndex(s => s >= SCORE_SCALE);
  SCORE_SCALE = ZOOM[Math.max(0, Math.min(ZOOM.length - 1, (i < 0 ? ZOOM.length : i) + step))];
  localStorage.scoreScale = SCORE_SCALE;
  const stabs = $(".stabs", activePanel());
  // keep the same part of the score in view as it grows or shrinks
  const top = stabs.getBoundingClientRect().top + scrollY, frac = (scrollY - top) / stabs.offsetHeight;
  renderScores(activePanel()).then(() => {
    if (frac > 0) scrollTo(0, top + frac * stabs.offsetHeight);
  });
}

// ---- per-version decoration, idempotent: re-run on every "rendered" -------
function decorate(panel) {
  const section = $("section[data-song]", panel);
  if (!section) return;  // the "add a version" panel
  if (!$(".mlisten", section)) {
    $(".flow", section).insertAdjacentHTML("beforebegin", `<div class="mlisten">
      <p class="mhint">Tap a pad to listen. Tap another to compare.</p>
      <div class="mgrid">${Object.keys(PADS).map(padHtml).join("")}</div></div>`);
    const grid = $(".mgrid", section);
    new ResizeObserver(() => drawPadArrows(grid)).observe(grid);
  }
  let files = $(".mfiles", panel);
  if (!files) {
    files = Object.assign(document.createElement("div"), { className: "mfiles" });
    $(".delver", panel).before(files);
  }
  const fh = filesHtml(section);
  if (files.dataset.html !== fh) files.innerHTML = files.dataset.html = fh;
  const scoreHead = $(".scorehead", section);
  if ($(".score[data-url]", section) && !$(".mzoom", scoreHead)) {
    $(".comment-toggle", scoreHead)?.insertAdjacentHTML("afterbegin", IC.talk);
    scoreHead.insertAdjacentHTML("beforeend", `<div class="mzoom">
      <button type="button" data-zoom="-1" aria-label="Smaller notes">−</button>
      <button type="button" data-zoom="1" aria-label="Bigger notes">+</button></div>`);
  }
  // the meter is set once per piece: it scrolls away instead of sticking
  const meter = $(".scorehead > .meter", section);
  if (meter) scoreHead.after(meter);
  // Undo is a ⋯ menu entry here, keeping the transport to one line
  const undo = $('.rec-bar > [data-action="undo"]', section);
  if (undo) {
    undo.className = "";
    undo.innerHTML = "<b>Undo last passage</b><span>Brings back what your last recording replaced</span>";
    $(".rec-menu", section).prepend(undo);
  }
}

function setTab(tab) {
  const recording = activeSection()?.recording?.supported;
  $('[data-tab="record"]', bar).hidden = !recording;
  if (tab === "record" && !recording) tab = "listen";
  html.dataset.mtab = tab;
  $$("[data-tab]", bar).forEach(b =>
    b.toggleAttribute("aria-current", b.dataset.tab === tab));
}

// Version picker, tab and add-form state after a build, refresh or switch.
function sync() {
  const btns = $$(".vtabs > .tabbar button[data-target]");
  const opts = btns.map(b => `<option value="${b.dataset.target}">${
    b.classList.contains("add") ? "+ Add a version…" : b.textContent}</option>`).join("");
  if (pick.dataset.html !== opts) pick.innerHTML = pick.dataset.html = opts;
  pick.value = btns.find(b => b.classList.contains("active"))?.dataset.target;
  html.classList.toggle("madd", pick.value === "v--__add");
  setTab(localStorage.mtab || "listen");
  paint();
}

document.addEventListener("rendered", () => {
  $$(".vtabs > .tabpanel").forEach(decorate);
  $("#gearmenu").append($("#gh-link"));
  sync();
});

// The last pad heard in each version, so the mini player and the score
// agree on "the current pad" (practice-audio fires no event when the
// backing changes while playing, so this is also polled).
document.addEventListener("play", e => {
  const section = e.target.closest?.("section[data-song]");
  if (section && keyOf(e.target)) cur[section.dataset.song] = keyOf(e.target);
}, true);

// ---- live state: ~4× a second, only for the visible version ----------------
function paint() {
  const section = activeSection();
  if (!section) { mini.hidden = true; html.classList.remove("mp-on"); return; }
  const v = section.dataset.song;
  const playing = $$(MEDIA, section).find(a => !a.paused);
  if (playing && keyOf(playing)) cur[v] = keyOf(playing);
  const el = mediaOf(section, cur[v]);
  const pos = el ? el.currentTime / duration(el) : 0;
  for (const pad of $$(".pad", section)) {
    const key = pad.dataset.key, p = padState(section, key);
    const cls = `pad ${p.st}${p.media && p.media === playing ? " playing" : ""}${
      p.media && key === cur[v] ? " cur" : ""}`;
    if (pad.className !== cls) {
      if (pad.dataset.st && pad.dataset.st !== "ready" && p.st === "ready" && !still.matches)
        pad.animate([{ opacity: .35 }, { opacity: 1 }], 700);
      pad.className = cls;
      pad.dataset.st = p.st;
      $(".pad-hit", pad).setAttribute("aria-label",
        `${PADS[key][0]}: ${p.st === "ready" ? (cls.includes("playing") ? "pause" : "play") : "details"}`);
    }
    const sub = p.st === "ready" ? readySub(section, key) : WAITING[p.st](p);
    const subEl = $(".pad-sub", pad);
    if (subEl.innerHTML !== sub) subEl.innerHTML = sub;
    pad.style.setProperty("--lvl", `${p.st === "arriving" ? 100 : p.pct ?? 0}%`);
    if (key === cur[v]) pad.style.setProperty("--pos", pos || 0);
  }
  mini.hidden = !el;
  html.classList.toggle("mp-on", !!el);
  if (!el) return;
  const [name, ic] = PADS[cur[v]];
  if ($("b", miniName).textContent !== name) {
    $("b", miniName).textContent = name;
    $(".tic", miniName).innerHTML = ic;
  }
  const d = duration(el);
  miniTime.textContent = `${clock(el.currentTime)} / ${clock(d)}`;
  if (document.activeElement !== miniRange) {
    miniRange.max = Number.isFinite(d) ? d : 0;
    miniRange.value = el.currentTime;
  }
  const label = el.paused ? "Play" : "Pause";
  if (miniBtn.getAttribute("aria-label") !== label) {
    miniBtn.setAttribute("aria-label", label);
    miniBtn.innerHTML = el.paused ? IC.play : IC.pause;
  }
}
setInterval(() => document.visibilityState === "visible" && paint(), 250);

// A comment sheet can cover the symbol just tapped: scroll it up above the sheet.
let tapY = 0;
document.addEventListener("pointerdown", e => { tapY = e.clientY; }, true);
new MutationObserver(() => {
  const menu = $("body > #fbmenu:not([data-placed])");
  if (!menu) return;
  menu.dataset.placed = "";
  const over = tapY - menu.getBoundingClientRect().top + 48;
  if (over > 0) scrollBy({ top: over, behavior: still.matches ? "auto" : "smooth" });
}).observe(document.body, { childList: true });
