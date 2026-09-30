// Prototype B, "Music stand": the phone sits on the stand while you play.
// The score gets the screen; one big transport dock at the bottom plays the
// source picked from the pipeline map. That map is the version's real .flow,
// restyled as a bottom sheet, so its players stay inside section[data-song]
// and bar highlighting, tap-a-bar and live progress keep working unchanged.
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const html = document.documentElement;
const smooth = () => matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth";

const NAMES = { src: "original", drumless: "without drums", drums: "drums stem" };
const CHIP = { src: "original", drumless: "no drums", drums: "drums" };
const SUB = { src: "the recording", drumless: "band only", drums: "drums only" };
const PARENTS = { drumless: ["src"], drums: ["src"], adtof: ["drums"],
                  mdx23c: ["drums"], fused: ["adtof", "mdx23c"] };
// [from, to, label, label beside the first ("trunk") or last ("tip") leg, side]
const LINKS = [["src", "drumless", "", "trunk", 1], ["src", "drums", "Demucs", "trunk", 1],
  ["drums", "adtof", "ADTOF", "tip", 1], ["drums", "mdx23c", "MDX23C", "tip", 1],
  ["adtof", "fused", "hits", "trunk", 1], ["mdx23c", "fused", "6 drum tracks", "trunk", -1]];
const SONI_TEXT = `You hear the original recording with a blip on every hit this
  pipeline found: low thump = kick, snappy noise = snare, high ticks = hi-hat
  and cymbals. A missing blip is a missed hit.`;

const icon = (d, size = 24) => `<svg viewBox="0 0 24 24" width="${size}" height="${size}"
  fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"
  stroke-linejoin="round" aria-hidden="true">${d}</svg>`;
const IC = {
  back: icon(`<path d="M15 5l-7 7 7 7"/>`),
  more: icon(`<g fill="currentColor"><circle cx="5" cy="12" r="1.6"/><circle cx="12" cy="12" r="1.6"/><circle cx="19" cy="12" r="1.6"/></g>`),
  close: icon(`<path d="M6 6l12 12M18 6L6 18"/>`),
  caret: icon(`<path d="M7 14l5-5 5 5"/>`, 16),
  down: icon(`<path d="M7 10l5 5 5-5"/>`, 16),
  play: icon(`<path d="M8 5.5v13l11-6.5z" fill="currentColor" stroke="none"/>`, 32),
  pause: icon(`<path d="M7 5h3.6v14H7zM13.4 5H17v14h-3.6z" fill="currentColor" stroke="none"/>`, 32),
  soni: `<svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
    stroke-linecap="round" aria-hidden="true"><path d="M4 15v3M8 13v7M12 15v3M16 12v9M20 15v3"/>
    <g fill="currentColor" stroke="none"><circle cx="8" cy="5.5" r="2.2"/><circle cx="16" cy="5.5" r="2.2"/></g></svg>`,
  help: icon(`<circle cx="12" cy="12" r="9"/><path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .8-1 1.5v.7"/><circle cx="12" cy="17" r=".6" fill="currentColor"/>`),
  follow: icon(`<path d="M4 6h16M4 10h16M4 14h7M4 18h7"/><path d="M17 13v7m-3-3l3 3 3-3"/>`),
  size: icon(`<path d="M4 19l5-14 5 14M6 14h6M16 19l3-8 3 8M17 16.5h4"/>`),
  meter: icon(`<path d="M3 12h18M3 6v12M12 6v12M21 6v12"/>`),
  rec: icon(`<circle cx="12" cy="12" r="6" fill="currentColor" stroke="none"/>`),
  log: icon(`<path d="M6 3h9l4 4v14H6z"/><path d="M9 11h7M9 15h7M9 7h4"/>`),
  trash: icon(`<path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13"/>`),
  gh: `<svg viewBox="0 0 16 16" width="22" height="22" fill="currentColor" aria-hidden="true">${
    $("#gh-link path")?.outerHTML ?? ""}</svg>`,
};
const ICONS = { src: IC_WAVE, drumless: IC_WAVE, drums: IC_DRUM };
const iconOf = key => ICONS[key] ?? IC.soni;
const nameOf = key => NAMES[key] ?? key;

// ---- chrome: top bar, sheets, transport dock --------------------------------
const song = PROJECT.replace(/-/g, " ");
document.body.insertAdjacentHTML("beforeend", `
<header class="mb-top">
  <a class="mb-ic" href="/" aria-label="All projects">${IC.back}</a>
  <button class="mb-title" data-open="versions" aria-label="Choose version">
    <b>${song[0].toUpperCase() + song.slice(1)}</b><span><span data-ver></span>${IC.down}</span></button>
  <button class="mb-ic" data-open="menu" aria-label="More">${IC.more}</button>
</header>
<div class="mb-scrim"></div>
<section class="mb-sheet" id="mb-versions" aria-label="Versions">
  <div class="mb-sheethead"><h2>Versions</h2>
    <button class="mb-ic" data-close aria-label="Close">${IC.close}</button></div>
  <div class="mb-vlist"></div>
  <button class="mb-addrow" aria-expanded="false">+ Add a version</button>
  <div class="mb-add" hidden></div>
</section>
<section class="mb-sheet" id="mb-menu" aria-label="More"></section>
<div class="mb-dock">
  <div class="mb-scrub"><output data-t>0:00</output>
    <input type="range" min="0" max="1" step="any" value="0" aria-label="Position in the song">
    <output data-d>0:00</output></div>
  <div class="mb-transport">
    <button class="mb-chip" data-open="source" aria-label="Choose what you hear">
      <span class="mb-chipic"><span data-srcic></span>${IC.caret}</span><span data-src></span></button>
    <button class="mb-step" data-step="-1" aria-label="Back one bar"><b>−1</b>bar</button>
    <button class="mb-play" aria-label="Play">${IC.play}</button>
    <button class="mb-step" data-step="1" aria-label="Forward one bar"><b>+1</b>bar</button>
    <div class="mb-bar" aria-live="off"><span>bar</span><b data-bar>–</b><small data-bars></small></div>
  </div>
</div>`);
const dock = $(".mb-dock"), range = $("input", dock), playBtn = $(".mb-play");

// ---- the active version and its selected source -----------------------------
const sec = () => $(".vtabs > .tabpanel.active section[data-song]");
const store = s => `mbSource:${PROJECT}/${s.dataset.song}`;
const mediaOf = (s, key) => $(`[data-piece="${key}"]`, s)?.querySelector(MEDIA);
let pending = null;  // a source still being decoded by the recording transport

// Whatever plays in this version is the dock's source (tap-a-bar, the
// recording view or the MuseScore plugin may have started it).
function selected(s) {
  const playing = $$(MEDIA, s).find(a => !a.paused);
  const key = playing?.closest("[data-piece]")?.dataset.piece;
  if (key && !pending) localStorage[store(s)] = key;
  const saved = pending ?? localStorage[store(s)];
  return mediaOf(s, saved) ? saved : "src";
}
const media = s => s && mediaOf(s, selected(s));

function duration(s, m) {
  const d = m?.tagName === "PRACTICE-AUDIO" ? m.owner?.duration
    : m?.tagName === "YT-AUDIO" ? m.yt?.getDuration?.() : m?.duration;
  const ok = x => x > 0 && isFinite(x);
  return ok(d) ? d : s && $$("audio", s).map(a => a.duration).find(ok) || 0;
}

function seek(m, t) {
  if (m.tagName === "AUDIO" && !m.readyState)  // must wait for metadata
    m.addEventListener("loadedmetadata", () => { m.currentTime = t; }, { once: true });
  else m.currentTime = t;
}

// Switching keeps the position, so one passage can be compared by ear.
function choose(key) {
  const s = sec(), old = media(s), next = mediaOf(s, key);
  if (!next) return;
  localStorage[store(s)] = key;
  lastAudio[s.dataset.song] = next;
  const rec = s.recording;
  if (rec?.supported) {  // one transport: it swaps the backing in place
    pending = key;
    rec.run(() => rec.selectBacking(key)).finally(() => { pending = null; });
  } else if (old && old !== next) {
    const playing = !old.paused, t = old.currentTime;
    old.pause();
    seek(next, t);
    if (playing) Promise.resolve(next.play()).catch(() => {});
  }
  renderDetail();
  tick();
}

let wantPlay = 0;
function toggle() {
  const s = sec(), m = media(s);
  if (!m) return;
  if (!m.paused) { wantPlay = 0; return m.pause(); }
  for (const a of $$(MEDIA, s)) if (a !== m && !a.paused) a.pause();
  lastAudio[s.dataset.song] = m;
  wantPlay = performance.now();
  Promise.resolve(m.play()).catch(() => {});
  tick();
}

const barAt = (bars, t) => {
  let n = 0;
  for (const b of bars) { if (b.t <= t + .05) n = b.bar; else break; }
  return n;
};
function step(d) {
  const s = sec(), m = media(s), bars = barTimes[s?.dataset.song];
  if (!m || !bars?.length) return;
  const n = Math.min(Math.max(barAt(bars, m.currentTime) + d, 1), bars.at(-1).bar);
  seek(m, Math.max(0, bars.find(b => b.bar === n).t - .04));
  setTimeout(tick, 60);
}

// ---- dock state, polled: practice-audio and yt-audio fire no pause events ---
const clock = t => `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, "0")}`;
let dragging = false;
function tick() {
  const s = sec(), key = s && selected(s), m = s && mediaOf(s, key);
  const t = m?.currentTime ?? 0, d = duration(s, m), playing = !!m && !m.paused;
  if (playing) wantPlay = 0;
  const loading = !playing && wantPlay && performance.now() - wantPlay < 8000;
  dock.classList.toggle("loading", !!loading);
  if (playBtn.dataset.playing !== String(playing)) {  // keep a finger's target
    playBtn.dataset.playing = playing;
    playBtn.innerHTML = playing ? IC.pause : IC.play;
    playBtn.setAttribute("aria-label", playing ? "Pause" : "Play");
  }
  playBtn.disabled = !m;
  if (!dragging) {
    range.max = d || 1;
    range.value = t;
    $("[data-t]", dock).textContent = clock(t);
  }
  range.style.setProperty("--p", `${Math.min(100, +range.value / (d || 1) * 100)}%`);
  $("[data-d]", dock).textContent = clock(d);
  const bars = s && barTimes[s.dataset.song];
  const n = bars ? barAt(bars, t) : 0;
  const total = bars?.at(-1)?.bar;  // before the first bar: "145 bars"
  $(".mb-bar span", dock).textContent = n || !total ? "bar" : "bars";
  $("[data-bar]", dock).textContent = n || total || "–";
  $("[data-bar]", dock).classList.toggle("none", !n);
  $("[data-bars]", dock).textContent = n && total ? `/${total}` : "";
  $(".mb-bar", dock).style.visibility = total ? "" : "hidden";
  $$(".mb-step", dock).forEach(b => b.disabled = !m || !bars?.length);
  if (key && $(".mb-chip", dock).dataset.key !== key) {
    $(".mb-chip", dock).dataset.key = key;
    $("[data-src]", dock).textContent = CHIP[key] ?? key;
    $("[data-srcic]", dock).innerHTML = iconOf(key);
  }
  $(".mb-chip", dock).classList.toggle("busy",
    !!s && !!$(".flow .prog:is(.running, .queued, .arriving)", s));
  if (!s) return;
  const flow = $(".flow", s);
  for (const node of $$(":scope > [data-piece]", flow)) {
    node.classList.toggle("mb-sel", node.dataset.piece === key);
    node.classList.toggle("mb-loading", node.dataset.piece === pending);
  }
  if (flow.classList.contains("mb-open")) drawMap(flow, key);
  if (playing) follow(s);
}
setInterval(tick, 250);

// ---- auto-follow: keep the playing bar in the middle band of the screen -----
let userScrolled = 0, followed = 0;
for (const type of ["touchmove", "wheel"])
  addEventListener(type, () => { userScrolled = performance.now(); }, { passive: true });
function follow(s) {
  const now = performance.now();
  if (localStorage.mbFollow === "off" || now - userScrolled < 4000 || now - followed < 700 ||
      html.dataset.sheet || $("#fbmenu")) return;
  const bar = $(".stabs > .tabpanel.active g.measure.now", s);
  if (!bar) return;
  const r = bar.getBoundingClientRect();
  const top = $(".scorehead", s).getBoundingClientRect().bottom;
  const h = dock.getBoundingClientRect().top - top;
  if (r.top >= top + h * .05 && r.bottom <= top + h * .6) return;
  followed = now;
  const by = r.top - top - h * .12;  // absolute target: robust mid-animation
  scrollTo({ top: scrollY + by, behavior: Math.abs(by) > innerHeight ? "instant" : smooth() });
}

// ---- pipeline map (the source sheet) ----------------------------------------
function decorate() {
  for (const s of $$("section[data-song]")) {
    const wait = $(".score.placeholder", s), flow = $(".flow", s);
    if (wait && !$(".mb-hint", wait) && mediaOf(s, "drums"))
      wait.insertAdjacentHTML("beforeend", `<button class="mb-hint" data-open="source">
        ${IC_DRUM}Meanwhile, listen to the drums and the band separately</button>`);
    if (!$(".mb-maphead", flow)) {
      flow.insertAdjacentHTML("afterbegin", `<div class="mb-maphead"><div>
        <h2>What you hear</h2><p>Switch while playing to compare by ear</p></div>
        <button class="mb-ic" data-close aria-label="Close">${IC.close}</button></div>`);
      flow.insertAdjacentHTML("beforeend", `<div class="mb-detail"></div>`);
    }
    for (const node of $$(":scope > [data-piece]", flow)) {
      if ($(".mb-sub", node)) continue;  // live refresh replaces whole pieces
      const key = node.dataset.piece, head = $("figcaption, .sonihead", node);
      if (!ICONS[key]) head.insertAdjacentHTML("afterbegin", IC.soni);
      const hits = $(".stats", node)?.textContent.match(/(\d+) hits/)?.[1];
      head.insertAdjacentHTML("afterend",
        `<span class="mb-sub">${SUB[key] ?? (hits ? `${hits} hits` : "")}</span>`);
    }
  }
}

// Own arrows (drawArrows can't follow a scrolling sheet): offsets inside the
// grid are scroll-proof. Legs leading to the chosen source are drawn in ink.
function drawMap(flow, key) {
  const at = k => {
    const el = $(`:scope > [data-piece="${k}"]`, flow);
    return { x: el.offsetLeft + el.offsetWidth / 2, top: el.offsetTop,
             bot: el.offsetTop + el.offsetHeight };
  };
  const on = new Set();
  (function up(k) { for (const p of PARENTS[k] ?? []) { on.add(`${p}>${k}`); up(p); } })(key);
  let out = "";
  for (const [a, b, label, where, side] of LINKS) {
    const A = at(a), B = at(b), y1 = A.bot + 3, y2 = B.top - 4, my = (A.bot + B.top) / 2;
    const r = Math.min(10, Math.abs(B.x - A.x) / 2), s = Math.sign(B.x - A.x);
    const d = s ? `M${A.x} ${y1}V${my - r}Q${A.x} ${my} ${A.x + s * r} ${my}H${B.x - s * r}
                   Q${B.x} ${my} ${B.x} ${my + r}V${y2}` : `M${A.x} ${y1}V${y2}`;
    const cls = on.has(`${a}>${b}`) ? "on" : "";
    const lx = (where === "trunk" ? A.x : B.x) + side * 8;
    const ly = where === "trunk" ? (y1 + my) / 2 + 5 : (my + y2) / 2 + 5;
    out += `<path class="${cls}" d="${d}" marker-end="url(#mb-arr${cls})"/>` + (label &&
      `<text class="${cls}" x="${lx}" y="${ly}" text-anchor="${side > 0 ? "start" : "end"}">${label}</text>`);
  }
  let svg = $(":scope > svg.mb-map", flow);
  if (!svg) {
    flow.insertAdjacentHTML("beforeend", `<svg class="mb-map" aria-hidden="true"></svg>`);
    svg = $(":scope > svg.mb-map", flow);
  }
  const marker = id => `<marker id="${id}" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="11"
    markerHeight="11" markerUnits="userSpaceOnUse" orient="auto"><path d="M0 0L8 4L0 8z"/></marker>`;
  const markup = `<defs>${marker("mb-arr")}${marker("mb-arron")}</defs>${out}`;
  if (svg.dataset.d !== markup) { svg.innerHTML = markup; svg.dataset.d = markup; }
}

function renderDetail() {
  const s = sec(), flow = s && $(".flow", s);
  if (!flow) return;
  const key = selected(s), node = $(`[data-piece="${key}"]`, flow);
  const soni = !ICONS[key];
  const stats = $(".stats", node)?.textContent.match(/\d+ hits, \d+ suspect/)?.[0];
  const dls = DOWNLOADS.map(([file, label]) => {
    const a = $(`a.doc[href$="/${file}"]`, node);
    return a && `<a class="mb-dl ${a.classList.contains("warn") ? "warn" : ""}"
      href="${a.getAttribute("href")}" download>${a.innerHTML}<span>${label}</span></a>`;
  }).filter(Boolean);
  const flac = $("a.download", node);
  if (flac) dls.push(`<a class="mb-dl" href="${flac.getAttribute("href")}"
    download="${flac.getAttribute("download")}">${IC_WAVE}<span>Without drums (FLAC)</span></a>`);
  $(".mb-detail", flow).innerHTML = `<h3>${iconOf(key)}${nameOf(key)}${soni ?
      " <small>sonification</small>" : ""}</h3>
    ${soni ? `<p>${SONI_TEXT}</p>` : ""}<p>${INFO[key === "src" ? "original" : key]}</p>
    ${stats ? `<p class="mb-stats">${stats}</p>` : ""}
    ${dls.length ? `<h4>Download</h4><div class="mb-dls">${dls.join("")}</div>` : ""}`;
}

// ---- sheets ------------------------------------------------------------------
function openSheet(which) {
  const was = html.dataset.sheet, s = sec();
  closeSheets();
  if (was === which) return;  // the same button closes it again
  const el = which === "source" ? s && $(".flow", s) : $(`#mb-${which}`);
  if (!el) return;
  ({ source: renderDetail, versions: renderVersions, menu: renderMenu })[which]();
  el.scrollTop = 0;
  el.classList.add("mb-open");
  html.dataset.sheet = which;
  tick();
}
function closeSheets() {
  $$(".mb-open").forEach(el => el.classList.remove("mb-open"));
  delete html.dataset.sheet;
}

function renderVersions() {
  const cur = sec()?.dataset.song;
  $(".mb-vlist").innerHTML = $$(".vtabs > .tabbar button[data-target]:not(.add)").map(b => {
    const name = b.dataset.target.slice(3), p = document.getElementById(b.dataset.target);
    const n = $$(".score[data-url]", p).length;
    const [cls, txt] = !$('[data-piece="err"]', p).hidden ? ["bad", "processing failed"]
      : $(".prog:is(.running, .arriving)", p) ? ["busy", "being transcribed…"]
      : $(".prog.queued", p) ? ["busy", "waiting its turn"]
      : ["", n ? `${n} score${n > 1 ? "s" : ""}` : "no score yet"];
    return `<button class="mb-vrow ${name === cur ? "on" : ""}" data-v="${b.dataset.target}"
      ${name === cur ? 'aria-current="true"' : ""}><b>${name}</b><span class="${cls}">${txt}</span></button>`;
  }).join("");
}

function switchVersion(target) {
  $$(MEDIA).forEach(a => a.pause());
  $(`.vtabs > .tabbar button[data-target="${target}"]`).click();
  closeSheets();
  scrollTo(0, 0);
  rescore();
  refresh();
}

const scalePct = () => Math.round(SCORE_SCALE / 45 * 100);
function renderMenu() {
  const s = sec(), name = s?.dataset.song, meter = s && $(".meter", s);
  const log = $$("#gearmenu a").find(a => a.textContent.endsWith(`— ${name}`));
  const follow = localStorage.mbFollow !== "off";
  const opts = meter ? $$(".mopt", meter) : [];
  const fixed = meter?.classList.contains("waiting");
  const row = (ic, label, extra = "", attrs = "", cls = "") =>
    `<button class="mb-mrow ${cls}" ${attrs}>${ic}<span>${label}</span>${extra}</button>`;
  $("#mb-menu").innerHTML = `<div class="mb-sheethead"><h2>${name ?? "Menu"}</h2>
    <button class="mb-ic" data-close aria-label="Close">${IC.close}</button></div>
  <div class="mb-group">
    ${row(IC.follow, "Follow the playing bar", `<i class="mb-switch"></i>`,
      `data-act="follow" role="switch" aria-checked="${follow}"`)}
    <div class="mb-mrow">${IC.size}<span>Score size</span>
      <span class="mb-zoom"><button data-act="zoom" data-d="-5" aria-label="Smaller"
        ${SCORE_SCALE <= 25 ? "disabled" : ""}>−</button><output>${scalePct()} %</output>
      <button data-act="zoom" data-d="5" aria-label="Larger"
        ${SCORE_SCALE >= 80 ? "disabled" : ""}>+</button></span></div>
    ${meter ? `<div class="mb-mrow mb-meter">${IC.meter}<span>Meter
      <small>${fixed ? "available once the beats are found"
        : opts[1]?.disabled ? "no uneven bars were heard, so it stays steady"
        : $(".mbusy", meter).hidden ? "changing keeps the barlines exactly as heard"
        : "recomputing the scores…"}</small></span>
      <span class="mb-mopts">${opts.map((b, i) => `<button data-act="meter" data-i="${i}"
        class="${b.classList.contains("active") ? "on" : ""}" ${b.disabled || fixed ? "disabled" : ""}
        aria-label="${i ? "changing" : "steady"} meter">${b.innerHTML}<small>${
        i ? "changing" : "steady"}</small></button>`).join("")}</span></div>` : ""}
  </div>
  ${s?.recording?.supported ? `<div class="mb-group">${row(IC.rec, "Record your own drums",
    `<i class="mb-switch"></i>`, `data-act="rec" role="switch" aria-checked="${
    html.classList.contains("mb-rec")}"`, "mb-recrow")}</div>` : ""}
  <div class="mb-group">
    ${row(IC.help, "Help", "", `data-act="help"`)}
    ${log ? `<a class="mb-mrow" href="${log.getAttribute("href")}">${IC.log}<span>Pipeline log</span></a>`
      : `<div class="mb-mrow quiet">${IC.log}<span>No pipeline log yet</span></div>`}
    <a class="mb-mrow" href="https://github.com/akaihola/drum-transcribe">${IC.gh}<span>Source code on GitHub</span></a>
  </div>
  ${name ? `<div class="mb-group">${row(IC.trash, "Delete this version", "",
    `data-act="delete"`, "danger")}</div>` : ""}`;
}

// ---- events ------------------------------------------------------------------
// Tap-a-bar plays the dock's source: seekToBar prefers the playing player,
// then lastAudio, so point both at it before the page's own handler runs.
document.addEventListener("click", e => {
  const s = e.target.closest(".score")?.closest("section[data-song]");
  if (!s || commentMode || e.target.closest("#fbmenu")) return;
  const m = media(s);
  for (const a of $$(MEDIA, s)) if (a !== m && !a.paused) a.pause();
  lastAudio[s.dataset.song] = m;
  if (s.recording?.supported) s.recording.run(() => s.recording.selectBacking(selected(s)));
}, true);

document.addEventListener("click", e => {
  const t = e.target;
  const el = t.closest("[data-open], [data-close], [data-act], [data-step], .mb-play, .mb-vrow, .mb-addrow, .mb-scrim");
  const tile = t.closest(".flow.mb-open > [data-piece]");
  if (tile) return tile.querySelector(MEDIA) && choose(tile.dataset.piece);
  if (!el) {  // a feedback sheet covering the tapped symbol: lift the score
    const fb = $("#fbmenu");
    if (fb && t.closest(".score")) {
      const top = fb.getBoundingClientRect().top;
      if (e.clientY > top - 32) scrollBy({ top: e.clientY - top + 96, behavior: smooth() });
    }
    return;
  }
  const act = el.dataset.act;
  if (el.dataset.open) openSheet(el.dataset.open);
  else if (el.matches("[data-close], .mb-scrim")) closeSheets();
  else if (el.dataset.step) step(+el.dataset.step);
  else if (el.matches(".mb-play")) toggle();
  else if (el.matches(".mb-vrow")) switchVersion(el.dataset.v);
  else if (el.matches(".mb-addrow")) {
    const add = $(".mb-add");
    add.hidden = !add.hidden;
    el.setAttribute("aria-expanded", !add.hidden);
    if (!add.hidden) add.scrollIntoView({ behavior: smooth(), block: "start" });
  } else if (act === "follow") {
    localStorage.mbFollow = localStorage.mbFollow === "off" ? "on" : "off";
    renderMenu();
  } else if (act === "zoom") {
    SCORE_SCALE = Math.min(80, Math.max(25, SCORE_SCALE + +el.dataset.d));
    localStorage.scoreScale = SCORE_SCALE;
    renderMenu();
    rescore();
  } else if (act === "meter") {
    $$(".mopt", sec())[+el.dataset.i].click();
    renderMenu();
  } else if (act === "rec") {
    html.classList.toggle("mb-rec");
    closeSheets();
    if (html.classList.contains("mb-rec"))
      $(".local-recording", sec()).scrollIntoView({ behavior: smooth() });
  } else if (act === "help") { closeSheets(); $("#help").showModal(); }
  else if (act === "delete") deleteVersion(sec().dataset.song);
});
addEventListener("keydown", e => { if (e.key === "Escape" && html.dataset.sheet) closeSheets(); });

// Drag a sheet down by its header to close it, as native sheets do.
let drag = null;
document.addEventListener("pointerdown", e => {
  const head = e.target.closest(".mb-open > :is(.mb-sheethead, .mb-maphead)");
  if (!head || e.target.closest("button")) return;
  drag = { sheet: head.parentElement, y: e.clientY };
  drag.sheet.style.transition = "none";
});
addEventListener("pointermove", e => {
  if (drag) drag.sheet.style.transform = `translateY(${Math.max(0, e.clientY - drag.y)}px)`;
});
for (const type of ["pointerup", "pointercancel"])
  addEventListener(type, e => {
    if (!drag) return;
    const { sheet, y } = drag;
    drag = null;
    sheet.style.transition = sheet.style.transform = "";
    if (e.clientY - y > 60) closeSheets();
  });

let dragTimer;
range.addEventListener("input", () => {
  dragging = true;
  $("[data-t]", dock).textContent = clock(+range.value);
  range.style.setProperty("--p", `${+range.value / +range.max * 100}%`);
});
range.addEventListener("change", () => {
  const m = media(sec());
  if (m) seek(m, +range.value);
  clearTimeout(dragTimer);
  dragTimer = setTimeout(() => { dragging = false; }, 300);  // let the seek land
});

// Scores are engraved at one scale; re-engrave only the version on show.
const engraved = new WeakMap();  // version panel -> SCORE_SCALE it was engraved at
function rescore() {
  const p = $(".vtabs > .tabpanel.active");
  if (!p || engraved.get(p) === SCORE_SCALE) return;
  engraved.set(p, SCORE_SCALE);
  renderScores(p);
}

function refresh() {
  const s = sec();
  $("[data-ver]").textContent = s?.dataset.song ?? "add a version";
  decorate();
  if (html.dataset.sheet === "source") renderDetail();
  if (html.dataset.sheet === "versions") renderVersions();
  tick();
}

let built = false;
document.addEventListener("rendered", () => {
  if (!built) {
    built = true;
    for (const p of $$(".vtabs > .tabpanel")) engraved.set(p, SCORE_SCALE);
    $(".mb-add").append($("#addform"));
    if (!sec()) { openSheet("versions"); $(".mb-addrow").click(); }  // nothing to show yet
  }
  refresh();
});
