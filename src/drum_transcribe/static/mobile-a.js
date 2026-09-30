// Prototype A, "Signal path" (phones only; picked in PROJECT_HTML's head).
// The pipeline becomes one column of collapsible cards on a git-graph rail.
// Uses the classic page script's globals by name (MEDIA, INFO, lastAudio,
// barTimes, SCORE_SCALE, renderScores, openFbMenu). Live refreshes replace
// whole [data-piece] elements, so every decoration is re-applied on each
// "rendered" event and skipped where it already exists.

const $ = (s, root = document) => root.querySelector(s);
const $$ = (s, root = document) => [...root.querySelectorAll(s)];
const icon = d => `<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">${d}</svg>`;
const stroke = d => icon(`<g fill="none" stroke="currentColor" stroke-width="2"
  stroke-linecap="round" stroke-linejoin="round">${d}</g>`);
const ICON = {
  play: icon(`<path d="M8.5 5.5v13l10.5-6.5z"/>`),
  pause: icon(`<path d="M7 5.5h3.5v13H7zM13.5 5.5H17v13h-3.5z"/>`),
  back: stroke(`<path d="M14.5 5.5 8 12l6.5 6.5"/>`),
  more: icon(`<circle cx="5" cy="12" r="2"/><circle cx="12" cy="12" r="2"/><circle cx="19" cy="12" r="2"/>`),
  comment: stroke(`<path d="M4.5 5.5h15v10h-9l-4.5 3.5v-3.5h-1.5z"/><path d="M8.5 9.5h7M8.5 12h4"/>`),
  zoomIn: stroke(`<circle cx="10.5" cy="10.5" r="6"/><path d="m15 15 5 5M8 10.5h5M10.5 8v5"/>`),
  zoomOut: stroke(`<circle cx="10.5" cy="10.5" r="6"/><path d="m15 15 5 5M8 10.5h5"/>`),
  down: stroke(`<path d="M12 4.5v11M7 11l5 5 5-5M5.5 19.5h13"/>`),
  mic: stroke(`<rect x="9" y="3.5" width="6" height="11" rx="3"/><path d="M6 11.5a6 6 0 0 0 12 0M12 17.5v3"/>`),
};

// Rail: two lanes in the left gutter, like a git graph. The trunk runs
// original → drums stem → adtof → fused; branches lead to the leaves.
const X = [12, 29], R = 5.5;
const LANE = { src: 0, drumless: 1, drums: 0, adtof: 0, mdx23c: 1, fused: 0 };
const EDGES = [["src", "drumless"], ["src", "drums"], ["drums", "adtof"],
               ["drums", "mdx23c"], ["adtof", "fused"], ["mdx23c", "fused"]];
// The rail shows where each card comes from; this line names the step.
const VIA = {
  drumless: "<b>Demucs</b> · from original",
  drums: "<b>Demucs</b> · from original",
  adtof: "<b>ADTOF</b> · from drums stem",
  mdx23c: "<b>MDX23C</b> · from drums stem",
  fused: "<b>hits</b> from adtof + <b>6 drum tracks</b> from mdx23c",
};
const WHAT = { src: "your recording", drumless: "the band without drums",
               drums: "the drums alone" };
const INFO_KEY = { src: "original", drums: "drums", drumless: "drumless" };
const SHORT = { "score.mscz": "MuseScore", "score.musicxml": "MusicXML", "audition.mid": "MIDI",
                "events.json": "events", "onsets.json": "raw hits", "feedback.json": "feedback" };

const opened = new Set();  // "version/piece" of open cards, kept across live refreshes
const reduced = matchMedia("(prefers-reduced-motion: reduce)");
const fmt = s => Number.isFinite(s) && s >= 0
  ? `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}` : "";
const duration = m => m.tagName === "AUDIO" ? m.duration
  : m.tagName === "YT-AUDIO" ? m.yt?.getDuration?.() : m.owner?.duration;
const songOf = el => el.closest("[data-song]")?.dataset.song;
const playing = () => $$(MEDIA).find(a => !a.paused);

// ---- header: back, title, help and menu in one row ------------------------
const top = document.createElement("header");
top.className = "ma-top";
top.innerHTML = `<a class="ma-ib" href="/" aria-label="All projects">${ICON.back}</a>`;
const gear = $("#gear-btn");
gear.innerHTML = ICON.more;
gear.setAttribute("aria-label", "Menu: pipeline logs and source code");
top.append($("#title"), $("#help-btn"), gear);
$("#app").before(top);
$('body > p > a[href="/"]')?.parentElement.remove();

// Floating "now playing" pill: lets a reader deep in the score stop playback.
const pill = document.createElement("div");
pill.className = "ma-now";
pill.hidden = true;
pill.innerHTML = `<button class="ma-now-go" type="button" aria-label="Show the bar being played">
  <span class="ma-eq"><i></i><i></i><i></i></span><b></b><span></span></button>
  <button class="ma-now-stop" type="button" aria-label="Pause">${ICON.pause}</button>`;
document.body.append(pill);

// ---- pipeline cards ---------------------------------------------------------
function dress(card) {
  const key = card.dataset.piece, media = $(MEDIA, card), prog = $(".prog", card);
  const name = $("figcaption b, .sonihead b", card).textContent;
  const hits = $(".stats", card)?.textContent.match(/(\d+) hits, (\d+) suspect/);
  const what = key === "src" && card.querySelector("yt-audio") ? "from YouTube" : WHAT[key];
  const head = document.createElement("div");
  head.className = "ma-head";
  head.innerHTML = (VIA[key] ? `<span class="ma-via">${VIA[key]}</span>` : "") +
    `<button class="ma-title" type="button" aria-expanded="false">${name}</button>
    <span class="ma-status">${hits ? `${hits[1]} hits · <em>${hits[2]} suspect</em>`
                                   : `${what}<span class="ma-dur"></span>`}</span>` +
    (media ? `<button class="ma-play" type="button" aria-label="Play ${name}">
               ${ICON.play}${ICON.pause}</button>` : "");
  if (prog) $(".ma-status", head).replaceChildren(prog);
  const body = document.createElement("div");
  body.className = "ma-body";
  body.innerHTML = `<p>${INFO[INFO_KEY[key] ?? key]}</p>` +
    (hits ? `<p class="ma-soni"><b>The ▶ button plays its sonification.</b> ${INFO.sonis}</p>` : "") +
    // YouTube's player shows its own strip instead (CSS), as phones may
    // want a first tap inside it before scripted play works.
    (media && media.tagName !== "YT-AUDIO" ? `<div class="ma-scrub"><input type="range" min="0" max="1000" value="0"
               aria-label="Position in ${name}"><output>0:00</output><output></output></div>` : "");
  // Touch has no hover tooltips: every download gets a visible name.
  const files = $$("a.doc, a.download", card);
  if (files.length) {
    const dl = document.createElement("div");
    dl.className = "ma-dl";
    for (const a of files) {
      if (a.matches(".download")) a.innerHTML = `${ICON.down}<span>Download FLAC
        <small>lossless, for Android and Ableton Live</small></span>`;
      else a.insertAdjacentHTML("beforeend", `<span>${SHORT[a.href.split("/").pop()]}</span>`);
      dl.append(a);
    }
    body.insertAdjacentHTML("beforeend", `<b class="ma-lbl">Downloads</b>`);
    body.append(dl);
    if ($(".warn", dl)) body.insertAdjacentHTML("beforeend", `<p class="ma-warn">MuseScore
      found problems in this file, so some bars may look wrong.</p>`);
  }
  card.prepend(head);
  card.append(body, Object.assign(document.createElement("i"), { className: "ma-line" }));
  setOpen(card, opened.has(`${songOf(card)}/${key}`));
}

function setOpen(card, open) {
  card.classList.toggle("ma-open", open);
  $(".ma-title", card).setAttribute("aria-expanded", open);
  const id = `${songOf(card)}/${card.dataset.piece}`;
  open ? opened.add(id) : opened.delete(id);
}

// An accordion: opening one card closes the others. The tapped row stays
// under the finger, and the opened card is scrolled fully into view.
function toggleCard(card) {
  const head = $(".ma-head", card), y = head.getBoundingClientRect().top;
  const open = !card.classList.contains("ma-open");
  $$(":scope > .ma-open", card.parentElement).forEach(c => setOpen(c, false));
  setOpen(card, open);
  scrollBy(0, head.getBoundingClientRect().top - y);
  const r = card.getBoundingClientRect();
  if (open && r.bottom > innerHeight - 80)
    scrollBy({ top: Math.min(r.bottom - innerHeight + 96, r.top - 12),
               behavior: reduced.matches ? "auto" : "smooth" });
  tick();
}

// All nodes of a version share one timeline, so a newly chosen source
// continues where the previous one was: compare by ear at the same spot.
// (practice-audio shares one transport already.)
function togglePlay(card) {
  const el = $(MEDIA, card);
  if (!el.paused) return el.pause();
  if (el.tagName !== "PRACTICE-AUDIO") {
    const from = playing() ?? lastAudio[songOf(card)];
    if (from && from !== el && songOf(from) === songOf(card)) el.currentTime = from.currentTime;
    $$(MEDIA).forEach(a => a !== el && !a.paused && a.pause());
  }
  el.play()?.catch?.(() => {});  // a refused autoplay just leaves it paused
  tick();
}

// ---- the rail ---------------------------------------------------------------
const rail = new ResizeObserver(entries => entries.forEach(e => drawRail(e.target)));

function drawRail(flow) {
  const svg = flow && $(":scope > svg.ma-rail", flow);
  if (!svg || !flow.clientHeight) return;
  const base = flow.getBoundingClientRect().top, y = {}, state = {};
  for (const card of $$(":scope > [data-piece]", flow)) {
    const t = $(".ma-title", card)?.getBoundingClientRect();
    if (!t) return;
    const k = card.dataset.piece;
    y[k] = t.top + t.height / 2 - base;
    state[k] = card.classList.contains("ma-playing") ? "play" : $(MEDIA, card) ? "ready"
      : $(".prog", card)?.classList[1] ?? "absent";
  }
  // "The signal flows here": light the path from the original to what plays.
  const lit = new Set();
  const up = k => { lit.add(k); EDGES.forEach(([a, b]) => b === k && up(a)); };
  const now = Object.keys(state).find(k => state[k] === "play");
  if (now) up(now);
  const edges = EDGES.map(([a, b]) => {
    const x1 = X[LANE[a]], x2 = X[LANE[b]], y1 = y[a] + R + 1.5, tip = y[b] - R - 2, y2 = tip - 6;
    const d = x1 === x2 ? `M${x1} ${y1}V${y2}`
      : x2 > x1 ? `M${x1} ${y1}C${x1} ${y1 + 14} ${x2} ${y1 + 6} ${x2} ${y1 + 20}V${y2}`
      : `M${x1} ${y1}V${y2 - 24}C${x1} ${y2 - 10} ${x2} ${y2 - 16} ${x2} ${y2}`;
    const cls = lit.has(b) ? "on" : ["ready", "play"].includes(state[b]) ? "" : "todo";
    return `<g class="${cls}"><path d="${d}"/><path class="tip" d="M${x2 - 4.5} ${y2}h9L${x2} ${tip}z"/></g>`;
  }).sort((a, b) => a.includes('"on"') - b.includes('"on"'));  // lit on top
  svg.innerHTML = edges.join("") + Object.keys(y).map(k =>
    `<circle class="${state[k]}${lit.has(k) ? " on" : ""}" cx="${X[LANE[k]]}" cy="${y[k]}" r="${R}"/>`).join("");
}

// Progress states colour the rail's dots, so redraw when they change.
const showProg = window.showProgress;
window.showProgress = (vname, prog) => {
  showProg(vname, prog);
  drawRail(document.getElementById(`v--${vname}`)?.querySelector(".flow"));
};

// ---- score ------------------------------------------------------------------
function dressScore(stabs) {
  stabs.dataset.ma = 1;
  const head = $(".scorehead", stabs), seg = $(".seg:not(.mseg)", head);
  if (!seg) return;  // no score yet: just the placeholder
  const toggle = $(".comment-toggle", head);
  toggle.innerHTML = `${ICON.comment}<span>Comment</span>`;
  toggle.setAttribute("aria-label", "Comment on symbols");
  head.insertAdjacentHTML("beforeend", `<p class="ma-hint">Tap any bar to play from there.</p>`);
  // The bar goes before .scorehead in the DOM (CSS shows it after) so that
  // refreshVersion still finds the selected score tab before the meter's.
  // Zoom sits by the heading: the sticky bar only has room for what a
  // reader deep in the score needs (score choice, comment switch).
  $(".grouplbl", head).insertAdjacentHTML("afterend", `<span class="ma-zoom">
    <button type="button" data-zoom="-5" aria-label="Smaller notes">${ICON.zoomOut}</button>
    <button type="button" data-zoom="5" aria-label="Bigger notes">${ICON.zoomIn}</button></span>`);
  const bar = document.createElement("div");
  bar.className = "ma-bar";
  bar.append(seg, toggle);
  bar.insertAdjacentHTML("beforeend", `<p class="ma-chint">Tap a note, or empty space in a
    bar, to say what is wrong there.</p>`);
  head.before(bar);
}

// Re-engrave at the new size, keeping the bar that was at the top in place.
async function zoom(step, stabs) {
  const next = Math.min(80, Math.max(30, SCORE_SCALE + step));
  if (next === SCORE_SCALE) return;
  const edge = Math.max(0, $(".ma-bar", stabs).getBoundingClientRect().bottom);
  const n = $$(".tabpanel.active g.measure[data-n]", stabs)
    .find(m => m.getBoundingClientRect().bottom > edge)?.dataset.n;
  SCORE_SCALE = next;
  localStorage.scoreScale = next;
  const section = stabs.closest("section");
  await renderScores(section);
  const m = n && $(`.tabpanel.active g.measure[data-n="${n}"]`, stabs);
  if (m) scrollBy(0, m.getBoundingClientRect().top - edge - 8);
  $$("section[data-song]").forEach(s => s !== section && renderScores(s));
}

// Feedback opens as a bottom sheet; mark the symbol it is about and keep it
// visible above the sheet.
const openMenu = window.openFbMenu;
window.openFbMenu = (sym, x, y) => {
  openMenu(sym, x, y);
  $$(".ma-sel").forEach(g => g.classList.remove("ma-sel"));
  sym.classList.add("ma-sel");
  const over = sym.getBoundingClientRect().bottom - $("#fbmenu").getBoundingClientRect().top + 24;
  if (over > 0) scrollBy({ top: over, behavior: reduced.matches ? "auto" : "smooth" });
};

// ---- live state: playing card, rail, progress lines, scrubbers, pill -------
let current;  // the card whose player is playing
function tick() {
  if (!$("#fbmenu")) $$(".ma-sel").forEach(g => g.classList.remove("ma-sel"));
  const el = playing(), card = el?.closest("[data-piece]");
  if (card !== current) {
    for (const c of [current, card]) {
      if (!c) continue;
      c.classList.toggle("ma-playing", c === card);
      $(".ma-play", c)?.setAttribute("aria-label",
        `${c === card ? "Pause" : "Play"} ${$(".ma-title", c).textContent}`);
      drawRail(c.parentElement);
    }
    current = card;
    pill.hidden = !card;
  }
  for (const c of $$(".vtabs > .tabpanel.active .flow > [data-piece]")) {
    const m = $(MEDIA, c);
    if (!m) continue;
    const d = duration(m), t = m.currentTime, dur = $(".ma-dur", c);
    if (dur && !dur.textContent && d) dur.textContent = ` · ${fmt(d)}`;
    if (c === card) c.style.setProperty("--pos", d ? Math.min(1, t / d) : 0);
    const range = $(".ma-scrub input", c);
    if (!c.classList.contains("ma-open") || !range || range.dataset.drag) continue;
    const [pos, total] = $$(".ma-scrub output", c);
    range.value = d ? t / d * 1000 : 0;
    pos.value = fmt(t);
    total.value = fmt(d);
  }
  if (!card) return;
  let bar = 0;
  for (const b of barTimes[songOf(card)] ?? []) { if (b.t <= el.currentTime + .05) bar = b.bar; else break; }
  $("b", pill).textContent = $(".ma-title", card).textContent;
  $(".ma-now-go > span:last-child", pill).textContent = bar ? `bar ${bar}` : fmt(el.currentTime);
}
setInterval(tick, 250);  // practice-audio and yt-audio fire no "pause" events

// Keep the chosen version's chip in view in the scrolling chip row.
function centerChip(chip, smooth) {
  const row = chip.parentElement;
  row.scrollTo({ behavior: smooth && !reduced.matches ? "smooth" : "auto",
    left: row.scrollLeft + chip.getBoundingClientRect().left - row.getBoundingClientRect().left
          - (row.clientWidth - chip.offsetWidth) / 2 });
}

document.addEventListener("rendered", () => {
  for (const flow of $$(".flow")) {
    $$(":scope > [data-piece]", flow).forEach(c => $(".ma-head", c) || dress(c));
    if (!$(":scope > svg.ma-rail", flow)) {
      flow.insertAdjacentHTML("afterbegin", `<svg class="ma-rail" aria-hidden="true"></svg>`);
      flow.insertAdjacentHTML("beforebegin", `<p class="ma-cap">The path from your recording
        to the drum score. Tap a row for details and downloads; ▶ plays it.</p>`);
      rail.observe(flow);
    }
    drawRail(flow);
  }
  $$(".stabs:not([data-ma])").forEach(dressScore);
  for (const rec of $$(".local-recording:not(details > *)")) {
    const ok = rec.closest("section").recording?.supported;
    rec.insertAdjacentHTML("beforebegin", `<details class="ma-rec"><summary>${ICON.mic}
      <span><b>Record your own drums</b><small>${ok ? "Play along with any track above, in this browser"
        : "Works only on a secure (https) address"}</small></span></summary></details>`);
    rec.previousElementSibling.append(rec);
  }
  const menu = $("#gearmenu");
  if (!$("#gh-link", menu)) {
    menu.insertAdjacentHTML("afterbegin", `<b>Pipeline logs</b>`);
    const gh = $("#gh-link");
    gh.insertAdjacentHTML("beforeend", "<span>Source code on GitHub</span>");
    menu.append(gh);
    const chip = $(".vtabs > .tabbar button.active");
    if (chip) centerChip(chip);
  }
  tick();
});

document.addEventListener("click", e => {
  const t = e.target;
  const play = t.closest(".ma-play");
  if (play) return togglePlay(play.closest("[data-piece]"));
  const head = t.closest(".ma-head");
  if (head) return toggleCard(head.parentElement);
  const z = t.closest("[data-zoom]");
  if (z) return zoom(+z.dataset.zoom, z.closest(".stabs"));
  if (t.closest(".ma-now-stop")) return playing()?.pause();
  if (t.closest(".ma-now-go"))
    return ($(".vtabs > .tabpanel.active .stabs .tabpanel.active g.measure.now") ?? current)
      ?.scrollIntoView({ block: "center", behavior: reduced.matches ? "auto" : "smooth" });
  const chip = t.closest(".vtabs > .tabbar button");
  if (chip) centerChip(chip, true);
});

// Scrubbing: show the time while dragging, seek on release. The seeked
// player becomes the one the next ▶ continues from.
document.addEventListener("input", e => {
  const range = e.target.closest?.(".ma-scrub input");
  if (!range) return;
  range.dataset.drag = 1;
  $(".ma-scrub output", range.parentElement).value =
    fmt(range.value / 1000 * duration($(MEDIA, range.closest("[data-piece]"))));
});
document.addEventListener("change", e => {
  const range = e.target.closest?.(".ma-scrub input");
  if (!range) return;
  delete range.dataset.drag;
  const card = range.closest("[data-piece]"), m = $(MEDIA, card);
  m.currentTime = range.value / 1000 * (duration(m) || 0);
  lastAudio[songOf(card)] = m;
});
