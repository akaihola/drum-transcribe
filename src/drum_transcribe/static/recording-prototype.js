// PROTOTYPE — throwaway, lives only on branch prototype/recording-ui.
// Three recording-UI variants mounted on the real project page, chosen with
// ?variant=A|B|C (variant=now shows the current UI). The transport is
// simulated: no sound, no microphone, nothing saved, real track untouched.
const NAMES = { now: "Current UI", A: "Transport dock", B: "Arrange view", C: "Console" };
const ORDER = Object.keys(NAMES);
const variant = new URLSearchParams(location.search).get("variant");
const PPS = 50; // waveform peaks per second
const SOURCES = [
  ["src", "Original", "ORIG"],
  ["drumless", "Without drums", "NO DRUMS"],
  ["drums", "Drums stem", "DRUMS"],
  ["adtof", "adtof blips", "ADTOF"],
  ["mdx23c", "mdx23c blips", "MDX23C"],
  ["fused", "fused blips", "FUSED"],
];
const label = (k) => SOURCES.find((s) => s[0] === k)?.[1] ?? k;
const I = {
  home: '<svg viewBox="0 0 24 24"><path d="M5 4h2.6v16H5zM20 4.5v15L9 12z"/></svg>',
  play: '<svg viewBox="0 0 24 24"><path d="M7 4.5v15l12-7.5z"/></svg>',
  pause: '<svg viewBox="0 0 24 24"><path d="M6 4h4.2v16H6zM13.8 4H18v16h-4.2z"/></svg>',
  rec: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="7"/></svg>',
  undo: '<svg viewBox="0 0 24 24"><path d="M9 7.5H4.5V3M5 8a8 8 0 1 1-.9 5" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/></svg>',
  more: '<svg viewBox="0 0 24 24"><circle cx="5" cy="12" r="2"/><circle cx="12" cy="12" r="2"/><circle cx="19" cy="12" r="2"/></svg>',
};

const S = {
  pos: 0, playing: false, mode: "playback", solo: false, backing: "drumless",
  band: -4.5, you: 0, mic: 6, phones: -8, takes: [], takeNo: 0, rec: null,
  undo: null, heard: null, flash: "", flashUntil: 0, view: "song", clip: false,
};
const D = { dur: 277, bars: [], beats: null, song: null, drums: null };
let cur = { sec: null, root: null };

const gain = (db) => (db <= -60 ? 0 : 10 ** (db / 20));
const dbText = (db) => (db <= -60 ? "−∞" : `${db > 0 ? "+" : db < 0 ? "−" : ""}${Math.abs(db).toFixed(1)} dB`);
const clock = (t) => `${Math.floor(t / 60)}:${(t % 60).toFixed(1).padStart(4, "0")}`;
const short = (t) => `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, "0")}`;
function barOf(t) {
  const b = D.beats;
  if (!b) return [1, 1];
  let i = b.times.findLastIndex((x) => x <= t);
  if (i < 0) return [1, 1];
  return [Math.max(1, D.bars.findLastIndex((x) => x <= t) + 1), b.positions[i]];
}
const barStart = (n) => D.bars[Math.max(0, Math.min(D.bars.length - 1, n - 1))] ?? 0;
const peakAt = (p, t) => (p ? p[Math.max(0, Math.min(p.length - 1, Math.floor(t * PPS)))] : 0);
const inTake = (t) => S.takes.some((r) => r.a <= t && t < r.b);
function flash(msg) {
  S.flash = msg;
  S.flashUntil = performance.now() + 2500;
}

// ---- simulated transport, following the settled behaviour -------------
function replace(list, a, b) {
  const out = [];
  for (const r of list)
    if (r.b <= a || r.a >= b) out.push(r);
    else {
      if (r.a < a) out.push({ ...r, b: a });
      if (r.b > b) out.push({ ...r, a: b });
    }
  out.push({ a, b, n: ++S.takeNo });
  return out.sort((x, y) => x.a - y.a);
}
function finishPassage() {
  if (S.rec != null && S.pos - S.rec > 0.05) {
    S.undo = S.takes;
    S.takes = replace(S.takes, S.rec, S.pos);
  }
  S.rec = null;
}
const A = {
  play() {
    if (S.playing) {
      finishPassage();
      S.playing = false;
    } else {
      S.playing = true;
      last = performance.now();
      if (S.mode === "record") S.rec = S.pos;
    }
  },
  rec() {
    if (S.mode === "record") {
      finishPassage();
      S.mode = "playback";
    } else {
      S.mode = "record";
      if (S.playing) S.rec = S.pos;
    }
  },
  mute() {
    finishPassage();
    S.mode = S.mode === "mute" ? "playback" : "mute";
  },
  solo() {
    S.solo = !S.solo;
  },
  home() {
    seek(0);
  },
  undo() {
    if (!S.undo) return;
    S.takes = S.undo;
    S.undo = null;
    flash("Last passage undone");
  },
  backing(k) {
    S.backing = k;
  },
  view(v) {
    S.view = v;
  },
  clip() {
    S.clip = false;
  },
  menu() {
    const m = cur.root?.querySelector("[data-menu]");
    if (m) m.hidden = !m.hidden;
  },
  export() {
    flash("Prototype: would download the whole song as WAV with the remembered mix");
  },
  import() {
    flash("Prototype: would open a file picker and replace your track");
  },
  clear() {
    if (!confirm("Clear your recording for this version? Download a copy first if you want to keep it.")) return;
    S.takes = [];
    S.undo = null;
    S.heard = null;
    flash("Your track is empty");
  },
};
function seek(t) {
  if (S.mode === "record") {
    finishPassage();
    S.mode = "playback";
    flash("Jumped — recording disarmed, your track plays back");
  }
  S.pos = Math.max(0, Math.min(D.dur, t));
}
let last = performance.now();
function advance(now) {
  const dt = (now - last) / 1000;
  last = now;
  if (!S.playing) return;
  S.pos += dt;
  if (S.mode === "playback" && !(S.takes.length === 0))
    S.heard = { backing: S.backing, band: S.band, you: S.you, solo: S.solo };
  if (S.pos >= D.dur) {
    S.pos = D.dur;
    finishPassage();
    S.playing = false;
    if (S.mode === "record") S.mode = "playback";
    flash("Song end — stopped");
  }
}

// ---- drawing ------------------------------------------------------------
function fit(cv) {
  const r = cv.getBoundingClientRect(), d = devicePixelRatio;
  const w = Math.round(r.width * d), h = Math.round(r.height * d);
  if (cv.width !== w || cv.height !== h) [cv.width, cv.height] = [w, h];
  const g = cv.getContext("2d");
  g.setTransform(d, 0, 0, d, 0, 0);
  g.clearRect(0, 0, r.width, r.height);
  return [g, r.width, r.height];
}
function view(w) {
  if (S.view === "song") return [0, D.dur];
  const [n] = barOf(S.pos), t0 = barStart(n - 2), t1 = barStart(n + 14);
  return [t0, Math.max(t1, t0 + 20)];
}
function wave(g, peaks, t0, t1, w, y, h, color, from = t0, to = t1) {
  if (!peaks) return;
  g.fillStyle = color;
  const a = Math.max(0, ((from - t0) / (t1 - t0)) * w), b = Math.min(w, ((to - t0) / (t1 - t0)) * w);
  for (let x = Math.floor(a); x < b; x++) {
    const k0 = Math.floor((t0 + (x / w) * (t1 - t0)) * PPS), k1 = Math.floor((t0 + ((x + 1) / w) * (t1 - t0)) * PPS);
    let m = 0;
    for (let k = k0; k <= k1 && k < peaks.length; k++) m = Math.max(m, peaks[k]);
    const hh = Math.max(0.5, (m * h) / 2);
    g.fillRect(x, y + h / 2 - hh, 1, hh * 2);
  }
}
function ruler(g, t0, t1, w, y, h, ink = "#6E675C") {
  const px = (t) => ((t - t0) / (t1 - t0)) * w;
  const perBar = D.bars.length > 1 ? px(D.bars[1]) - px(D.bars[0]) : 10;
  const every = [1, 2, 4, 8, 16, 32].find((n) => n * perBar > 34) ?? 64;
  g.font = "11px 'Alegreya Sans', sans-serif";
  g.textBaseline = "top";
  D.bars.forEach((t, i) => {
    if (t < t0 || t > t1) return;
    const x = Math.round(px(t)) + 0.5, major = (i + 1) % every === 0 || i === 0;
    g.fillStyle = ink;
    g.globalAlpha = major ? 0.9 : 0.35;
    g.fillRect(x, y + (major ? 0 : h * 0.55), 1, major ? h : h * 0.45);
    if (major) g.fillText(String(i + 1), x + 3, y + 1);
  });
  g.globalAlpha = 1;
}
function takes(g, t0, t1, w, y, h, { muted, boxes = true } = {}) {
  const px = (t) => ((t - t0) / (t1 - t0)) * w;
  const teal = muted ? "#A9A296" : "#0E7386";
  for (const r of S.takes) {
    if (r.b < t0 || r.a > t1) continue;
    if (S.rec != null && r.a >= S.rec && r.a < S.pos) continue;
    const a = Math.max(0, px(r.a)), b = Math.min(w, px(r.b));
    if (boxes) {
      g.fillStyle = muted ? "rgba(110,103,92,.10)" : "rgba(14,115,134,.10)";
      g.fillRect(a, y, b - a, h);
      g.fillStyle = teal;
      g.fillRect(a, y, b - a, 2);
      if (b - a > 70) {
        g.font = "11px 'Alegreya Sans', sans-serif";
        g.textBaseline = "top";
        g.fillText(`take ${r.n} · bars ${barOf(r.a)[0]}–${barOf(r.b - 0.01)[0]}`, a + 4, y + 4);
      }
    }
    wave(g, D.drums, t0, t1, w, y + (boxes ? 8 : 0), h - (boxes ? 8 : 0), teal, r.a, r.b);
  }
  if (S.rec != null) {
    const a = Math.max(0, px(S.rec)), b = Math.min(w, px(S.pos));
    g.fillStyle = "rgba(196,0,0,.12)";
    g.fillRect(a, y, b - a, h);
    g.fillStyle = "#C40000";
    g.fillRect(a, y, b - a, 2);
    wave(g, D.drums, t0, t1, w, y + (boxes ? 8 : 0), h - (boxes ? 8 : 0), "#C40000", S.rec, S.pos);
  }
}
function playhead(g, t0, t1, w, h) {
  const x = Math.round(((S.pos - t0) / (t1 - t0)) * w) + 0.5;
  g.fillStyle = S.rec != null ? "#C40000" : "#232019";
  g.fillRect(x - 0.5, 0, 1.5, h);
}
function backingPeaks() {
  return S.backing === "drums" ? D.drums : D.song;
}

// ---- data ---------------------------------------------------------------
async function peaksOf(url) {
  const bytes = await (await fetch(url)).arrayBuffer();
  const buf = await new OfflineAudioContext(1, 1, 8000).decodeAudioData(bytes);
  const step = buf.sampleRate / PPS, out = new Float32Array(Math.ceil(buf.duration * PPS) + 1);
  for (let c = 0; c < buf.numberOfChannels; c++) {
    const d = buf.getChannelData(c);
    for (let i = 0; i < d.length; i++) {
      const k = (i / step) | 0, v = d[i] < 0 ? -d[i] : d[i];
      if (v > out[k]) out[k] = v;
    }
  }
  return [out, buf.duration];
}
async function load(v) {
  D.song = D.drums = D.beats = null;
  D.bars = [];
  const beats = await (await fetch(v.beats)).json();
  D.beats = beats;
  D.bars = beats.times.filter((_, i) => beats.positions[i] === 1);
  S.takes = [
    { a: barStart(9), b: barStart(17), n: 1 },
    { a: barStart(25), b: barStart(41), n: 2 },
  ];
  S.takeNo = 2;
  [D.song, D.dur] = await peaksOf(v.source);
  [D.drums] = await peaksOf(v.drums);
}

// ---- shared bits of markup ------------------------------------------------
const fader = (k, min = -60, max = 6, cls = "") =>
  `<input type="range" class="${cls}" data-level="${k}" min="${min}" max="${max}" step="0.5" value="${S[k]}" aria-label="${k} level">`;
const out = (k) => `<output data-db="${k}">${dbText(S[k])}</output>`;
const meter = (k, dir = "h") => `<span class="pt-meter pt-${dir}" data-meter="${k}"><i></i><em></em></span>`;
const exportInfo = () =>
  `<div class="pt-mixnote" data-heard></div>`;
function heardText() {
  const h = S.heard;
  return h
    ? `Remembered mix: ${h.solo ? "your track solo" : `${label(h.backing)} ${dbText(h.band)} + you ${dbText(h.you)}`}`
    : "Nothing heard with your track yet — the file would be your track alone";
}
const menu = () => `<div class="pt-menu" data-menu hidden>
  <button data-pa="export"><b>Export WAV</b><span data-heard></span></button>
  <button data-pa="import"><b>Import audio…</b><span>Replaces your track, starting at 0:00</span></button>
  <label><b>Latency correction</b><span><input type="number" value="60" min="0" max="1000"> ms — places new takes earlier to match what you heard</span></label>
  <button data-pa="clear" class="pt-danger"><b>Clear your track…</b><span>Frees this version's recording in the browser</span></button>
</div>`;
function status() {
  if (performance.now() < S.flashUntil) return S.flash;
  const [bar] = barOf(S.pos);
  if (S.mode === "record")
    return S.playing
      ? `Recording since bar ${barOf(S.rec ?? S.pos)[0]} — only what the playhead crosses is replaced`
      : `Armed — press ▶ (Space) to record from bar ${bar}`;
  if (S.mode === "mute") return `Your track muted · hearing ${label(S.backing)}`;
  return S.solo ? "Your track solo" : `Hearing ${label(S.backing)} + your track`;
}

// ---- variant A: transport dock ------------------------------------------
function mountA() {
  const el = document.createElement("div");
  el.className = "pt-root ptA";
  el.innerHTML = `
    <div class="ptA-tr">
      <button class="pt-k" data-pa="home" title="Back to start (Home)">${I.home}</button>
      <button class="pt-k big play" data-pa="play" title="Play / pause (Space)">${I.play}</button>
      <button class="pt-k big rec" data-pa="rec" title="Record (R)">${I.rec}</button>
    </div>
    <div class="ptA-count"><div><b data-bar>1.1</b><small>bar</small></div><span data-time></span></div>
    <div class="ptA-ov"><div class="ptA-st" data-status></div><canvas data-draw="overview" data-seek></canvas></div>
    <div class="ptA-mix">
      <div><span>Band</span>${fader("band")}${out("band")}</div>
      <div><span>You</span>${fader("you")}${out("you")}
        <button class="pt-t m" data-pa="mute" title="Mute your track (M)">M</button><button class="pt-t s" data-pa="solo" title="Solo your track (S)">S</button></div>
    </div>
    <div class="ptA-mic"><div><span>Mic</span>${meter("mic")}<button class="pt-clip" data-pa="clip" title="Clipped — click to reset">CLIP</button></div>
      <div><span>gain</span>${fader("mic", -12, 24)}${out("mic")}</div></div>
    <div class="ptA-tools">
      <button class="pt-k" data-pa="undo" title="Undo last passage (Ctrl+Z)">${I.undo}</button>
      <button class="pt-k" data-pa="menu" title="Export, import, clear, latency">${I.more}</button>
      <span class="pt-saved">✓ saved in this browser</span>${menu()}
    </div>`;
  document.body.append(el);
  document.body.classList.add("ptA-pad");
  return el;
}
function drawA(root) {
  const cv = root.querySelector('[data-draw="overview"]');
  const [g, w, h] = fit(cv), t0 = 0, t1 = D.dur;
  cv._view = [t0, t1];
  ruler(g, t0, t1, w, 0, 13);
  const soloed = S.solo && S.mode === "playback";
  g.globalAlpha = soloed ? 0.25 : 1;
  wave(g, backingPeaks(), t0, t1, w, 16, h - 16, "#DCD6CA");
  g.globalAlpha = 1;
  takes(g, t0, t1, w, 16, h - 16, { muted: S.mode === "mute", boxes: false });
  playhead(g, t0, t1, w, h);
}

// ---- variant B: arrange view --------------------------------------------
function mountB(sec) {
  const el = document.createElement("section");
  el.className = "pt-root ptB";
  el.innerHTML = `
    <div class="ptB-tb">
      <div class="ptB-tr">
        <button class="pt-k" data-pa="home" title="Back to start (Home)">${I.home}</button>
        <button class="pt-k play" data-pa="play" title="Play / pause (Space)">${I.play}</button>
        <button class="pt-k rec" data-pa="rec" title="Record (R)">${I.rec}</button>
      </div>
      <div class="ptB-count"><b data-bar>1.1</b><span data-time></span></div>
      <button class="pt-k" data-pa="undo" title="Undo last passage (Ctrl+Z)">${I.undo}</button>
      <div class="pt-seg"><button data-pa="view" data-pv="song">Whole song</button><button data-pa="view" data-pv="follow">Follow 16 bars</button></div>
      <div class="ptB-st" data-status></div>
      <span class="pt-saved">✓ saved in this browser</span>
      <button class="pt-k" data-pa="menu" title="Export, import, clear, latency">${I.more}</button>${menu()}
    </div>
    <div class="ptB-grid">
      <div class="ptB-hd ptB-rh">bars</div><canvas data-draw="ruler" data-seek></canvas>
      <div class="ptB-hd">
        <div class="ptB-name">Backing</div>
        <select data-backing aria-label="Backing">${SOURCES.map(([k, l]) => `<option value="${k}">${l}</option>`).join("")}</select>
        <div class="ptB-f">${fader("band")}${out("band")}</div>${meter("band", "v")}
      </div><canvas data-draw="backing" data-seek></canvas>
      <div class="ptB-hd you">
        <div class="ptB-name">Your drums
          <span class="ptB-btns"><button class="pt-t r" data-pa="rec" title="Record arm (R)">${I.rec}</button><button class="pt-t m" data-pa="mute" title="Mute (M)">M</button><button class="pt-t s" data-pa="solo" title="Solo (S)">S</button></span></div>
        <div class="ptB-f">${fader("you")}${out("you")}</div>
        <div class="ptB-f mic"><span>mic</span>${fader("mic", -12, 24)}${out("mic")}<button class="pt-clip" data-pa="clip">CLIP</button></div>
        ${meter("mic", "v")}
      </div><canvas data-draw="you" data-seek></canvas>
    </div>`;
  sec.querySelector(".flow").after(el);
  return el;
}
function drawB(root) {
  const [t0, t1] = view();
  for (const cv of root.querySelectorAll("canvas")) {
    const [g, w, h] = fit(cv);
    cv._view = [t0, t1];
    const k = cv.dataset.draw;
    if (k === "ruler") ruler(g, t0, t1, w, 4, h - 4, "#232019");
    else {
      D.bars.forEach((t, i) => {
        g.fillStyle = i % 4 === 0 ? "rgba(35,32,25,.10)" : "rgba(35,32,25,.04)";
        if (t >= t0 && t <= t1) g.fillRect(((t - t0) / (t1 - t0)) * w, 0, 1, h);
      });
      if (k === "backing") {
        g.globalAlpha = S.solo && S.mode === "playback" ? 0.25 : 1;
        wave(g, backingPeaks(), t0, t1, w, 6, h - 12, "#8C8579");
        g.globalAlpha = 1;
      } else takes(g, t0, t1, w, 4, h - 8, { muted: S.mode === "mute" });
    }
    playhead(g, t0, t1, w, h);
  }
}

// ---- variant C: console ---------------------------------------------------
const scale = `<span class="ptC-scale">${[6, 0, -6, -12, -24, -48].map((d) => `<i style="bottom:${((d + 60) / 66) * 100}%">${d > 0 ? "+" : ""}${d}</i>`).join("")}<i style="bottom:0">−∞</i></span>`;
function mountC(sec) {
  const el = document.createElement("section");
  el.className = "pt-root ptC";
  el.innerHTML = `
    <div class="ptC-deck">
      <div class="ptC-lcd"><div><small>BAR</small><b data-bar>1.1</b></div><div><small>TIME</small><b data-time></b></div><div class="ptC-mode" data-lcdmode></div></div>
      <div class="ptC-keys">
        <button class="ptC-key" data-pa="home" title="Back to start (Home)">${I.home}<small>START</small></button>
        <button class="ptC-key play" data-pa="play" title="Play / pause (Space)">${I.play}<small>PLAY</small></button>
        <button class="ptC-key rec" data-pa="rec" title="Record (R)">${I.rec}<small>REC</small></button>
        <button class="ptC-key" data-pa="undo" title="Undo last passage (Ctrl+Z)">${I.undo}<small>UNDO</small></button>
      </div>
      <div class="ptC-ov"><canvas data-draw="overview" data-seek></canvas><div class="ptC-st" data-status></div></div>
    </div>
    <div class="ptC-desk">
      <div class="ptC-strip">
        <h4>Backing</h4>
        <div class="ptC-srcs">${SOURCES.map(([k, , s]) => `<button data-pa="backing" data-pv="${k}">${s}</button>`).join("")}</div>
        <div class="ptC-fz">${scale}${fader("band", -60, 6, "pt-vf")}${meter("band", "v")}</div>${out("band")}
      </div>
      <div class="ptC-strip you">
        <h4>Your drums</h4>
        <div class="ptC-in"><div class="pt-knob" data-knob="mic" title="Mic gain — drag up/down"><i></i></div>
          <div><small>MIC GAIN</small>${out("mic")}<button class="pt-clip" data-pa="clip">CLIP</button></div></div>
        <div class="ptC-btns"><button class="pt-t r" data-pa="rec" title="Record arm (R)">${I.rec}</button><button class="pt-t m" data-pa="mute" title="Mute (M)">M</button><button class="pt-t s" data-pa="solo" title="Solo (S)">S</button></div>
        <div class="ptC-fz">${meter("mic", "v")}${scale}${fader("you", -60, 6, "pt-vf")}${meter("you", "v")}</div>${out("you")}
      </div>
      <div class="ptC-strip phones">
        <h4>Headphones</h4>
        <p>Listening only — never changes the exported file</p>
        <div class="ptC-fz">${scale}${fader("phones", -60, 6, "pt-vf")}${meter("phones", "v")}</div>${out("phones")}
      </div>
      <div class="ptC-rack">
        <h4>Track</h4>
        <button data-pa="export"><b>Export WAV</b><span data-heard></span></button>
        <button data-pa="import"><b>Import audio…</b><span>Replaces your track from 0:00</span></button>
        <label><b>Latency correction</b><span><input type="number" value="60" min="0" max="1000"> ms</span></label>
        <button data-pa="clear" class="pt-danger"><b>Clear track…</b></button>
        <span class="pt-saved">✓ saved in this browser</span>
      </div>
    </div>`;
  sec.querySelector(".flow").after(el);
  const knob = el.querySelector("[data-knob]");
  knob.onpointerdown = (e) => {
    knob.setPointerCapture(e.pointerId);
    const y0 = e.clientY, v0 = S.mic;
    knob.onpointermove = (m) => {
      S.mic = Math.max(-12, Math.min(24, Math.round((v0 + (y0 - m.clientY) / 4) * 2) / 2));
      sync();
    };
    knob.onpointerup = () => (knob.onpointermove = null);
  };
  return el;
}
function drawC(root) {
  const cv = root.querySelector('[data-draw="overview"]');
  const [g, w, h] = fit(cv), t0 = 0, t1 = D.dur;
  cv._view = [t0, t1];
  ruler(g, t0, t1, w, 0, 12, "#9FD3DC");
  takes(g, t0, t1, w, 15, h - 15, { muted: S.mode === "mute", boxes: false });
  playhead(g, t0, t1, w, h);
  g.fillStyle = "#E8F3F4";
  g.fillRect(Math.round((S.pos / D.dur) * w), 0, 1.5, h);
}

// ---- meters (mock levels from the real waveforms) -----------------------
const hold = {};
function levels() {
  const playingBack = S.playing && S.mode === "playback" && inTake(S.pos);
  const band = S.playing && !(S.solo && S.mode === "playback") ? peakAt(backingPeaks(), S.pos) * gain(S.band) : 0;
  const you = playingBack ? peakAt(D.drums, S.pos) * gain(S.you) : 0;
  const armedT = S.playing ? S.pos : (performance.now() / 1000) % D.dur;
  const mic = S.mode === "record" ? peakAt(D.drums, armedT) * 0.6 * gain(S.mic) : 0;
  if (mic > 1) S.clip = true;
  return { band, you, mic, phones: Math.min(1.2, band + you) * gain(S.phones) };
}
function meters(root) {
  const lv = levels();
  for (const m of document.querySelectorAll(".pt-root [data-meter]")) {
    const k = m.dataset.meter, db = lv[k] > 0 ? 20 * Math.log10(lv[k]) : -99;
    const p = Math.max(0, Math.min(1, (db + 48) / 48));
    const hk = hold[k] ?? { v: 0, t: 0 };
    if (p >= hk.v || performance.now() - hk.t > 1200) hold[k] = { v: p, t: performance.now() };
    m.style.setProperty("--lv", p);
    m.style.setProperty("--pk", hold[k].v);
  }
}

// ---- sync: state → DOM ----------------------------------------------------
function sync() {
  const root = cur.root;
  document.documentElement.dataset.ptMode = S.mode;
  for (const b of document.querySelectorAll('[data-pa="play"]')) {
    if (b._playing !== S.playing)
      b.innerHTML = (S.playing ? I.pause : I.play) + (b.querySelector("small")?.outerHTML ?? "");
    b._playing = S.playing;
    b.classList.toggle("on", S.playing);
  }
  for (const b of document.querySelectorAll('[data-pa="rec"]')) {
    b.classList.toggle("armed", S.mode === "record" && !S.playing);
    b.classList.toggle("live", S.mode === "record" && S.playing);
  }
  for (const b of document.querySelectorAll('[data-pa="mute"]')) b.classList.toggle("on", S.mode === "mute");
  for (const b of document.querySelectorAll('[data-pa="solo"]')) b.classList.toggle("on", S.solo);
  for (const b of document.querySelectorAll('[data-pa="backing"]')) b.classList.toggle("on", b.dataset.pv === S.backing);
  for (const b of document.querySelectorAll('[data-pa="view"]')) b.classList.toggle("on", b.dataset.pv === S.view);
  for (const b of document.querySelectorAll('[data-pa="undo"]')) b.disabled = !S.undo;
  for (const b of document.querySelectorAll('[data-pa="clip"]')) b.classList.toggle("on", S.clip);
  for (const f of document.querySelectorAll(".pt-pickcard")) f.classList.toggle("pt-sel", f.dataset.piece === S.backing);
  if (!root) return;
  root.classList.toggle("is-rec", S.mode === "record" && S.playing);
  root.classList.toggle("is-armed", S.mode === "record" && !S.playing);
  root.classList.toggle("is-mute", S.mode === "mute");
  root.classList.toggle("is-solo", S.solo);
  const select = root.querySelector("select[data-backing]");
  if (select) select.value = S.backing;
  for (const o of root.querySelectorAll("[data-db]")) o.textContent = dbText(S[o.dataset.db]);
  for (const i of root.querySelectorAll("[data-level]")) if (document.activeElement !== i) i.value = S[i.dataset.level];
  for (const e of root.querySelectorAll("[data-heard]")) e.textContent = heardText();
  const knob = root.querySelector("[data-knob] i");
  if (knob) knob.style.rotate = `${((S.mic + 12) / 36) * 270 - 135}deg`;
  const lcd = root.querySelector("[data-lcdmode]");
  if (lcd) lcd.textContent = S.mode === "record" ? (S.playing ? "● REC" : "ARMED") : S.playing ? "▶ PLAY" : "■ STOP";
}
function frame(now) {
  advance(now);
  const root = cur.root;
  if (root && D.beats) {
    const [bar, beat] = barOf(S.pos);
    for (const e of root.querySelectorAll("[data-bar]")) e.textContent = `${bar}.${beat}`;
    for (const e of root.querySelectorAll("[data-time]"))
      e.textContent = variant === "C" ? clock(S.pos) : `${clock(S.pos)} / ${short(D.dur)}`;
    for (const e of root.querySelectorAll("[data-status]")) e.textContent = status();
    ({ A: drawA, B: drawB, C: drawC })[variant]?.(root);
    meters(root);
    sync();
  }
  stateLine();
  requestAnimationFrame(frame);
}

// ---- mounting on the live page ------------------------------------------
function decorate(sec) {
  for (const [k] of SOURCES) {
    const fig = sec.querySelector(`.player[data-piece="${k}"]`);
    if (!fig || fig.querySelector(".pt-pick")) continue;
    fig.classList.add("pt-pickcard");
    const b = document.createElement("button");
    b.className = "pt-pick";
    b.dataset.pa = "backing";
    b.dataset.pv = k;
    b.innerHTML = `<span class="pt-dot"></span><span class="pt-on">Backing</span><span class="pt-off">Use as backing</span>`;
    const player = fig.querySelector("practice-audio");
    player ? player.before(b) : fig.append(b);
  }
}
function ensure() {
  const sec = document.querySelector(".tabpanel.active section[data-song]");
  if (!sec?.recording) return;
  if (sec !== cur.sec) {
    cur.root?.remove();
    cur = { sec, root: null };
    load(sec.recording.version).catch((e) => flash(`Prototype data failed: ${e.message}`));
  }
  if (variant === "now") return;
  document.body.classList.add("pt-on");
  decorate(sec);
  if (!cur.root || !document.contains(cur.root))
    cur.root = ({ A: mountA, B: mountB, C: mountC })[variant](sec);
}

// ---- the prototype switcher (not part of any design) -------------------
function switcher() {
  const bar = document.createElement("div");
  bar.className = "pt-switch";
  const i = ORDER.indexOf(variant);
  const go = (d) => {
    const u = new URL(location.href);
    u.searchParams.set("variant", ORDER[(i + d + ORDER.length) % ORDER.length]);
    location.href = u;
  };
  bar.innerHTML = `<button aria-label="previous variant">‹</button><div><b>${variant} — ${NAMES[variant]}</b><small data-state></small></div><button aria-label="next variant">›</button>`;
  const [prev, next] = bar.querySelectorAll("button");
  prev.onclick = () => go(-1);
  next.onclick = () => go(1);
  document.body.append(bar);
  addEventListener("keydown", (e) => {
    if (e.target.closest?.("input,select,textarea,[contenteditable]")) return;
    if (e.key === "ArrowLeft") go(-1);
    else if (e.key === "ArrowRight") go(1);
  });
}
function stateLine() {
  const e = document.querySelector(".pt-switch [data-state]");
  if (e)
    e.textContent = `prototype, no sound · mode=${S.mode}${S.playing ? " playing" : " paused"}${S.solo ? " solo" : ""} · ${short(S.pos)} · backing=${S.backing} · takes=${S.takes.length}${S.undo ? " · undo" : ""}`;
}

function start() {
  const css = document.createElement("link");
  css.rel = "stylesheet";
  css.href = "/static/recording-prototype.css";
  document.head.append(css);
  switcher();
  document.body.dataset.pt = variant;
  if (variant !== "now") {
    document.addEventListener("click", (e) => {
      const b = e.target.closest("[data-pa]");
      if (!b) {
        if (!e.target.closest(".pt-menu")) cur.root?.querySelectorAll("[data-menu]").forEach((m) => (m.hidden = true));
        return;
      }
      e.preventDefault();
      A[b.dataset.pa]?.(b.dataset.pv);
      b.blur();
      sync();
    });
    document.addEventListener("input", (e) => {
      const k = e.target.dataset?.level;
      if (k) S[k] = +e.target.value;
      if (e.target.matches?.("[data-backing]")) S.backing = e.target.value;
      sync();
    });
    document.addEventListener("change", (e) => {
      if (e.target.matches?.("[data-backing]")) S.backing = e.target.value;
    });
    document.addEventListener("pointerdown", (e) => {
      const cv = e.target.closest?.("canvas[data-seek]");
      if (!cv?._view) return;
      const at = (ev) => {
        const r = cv.getBoundingClientRect(), [t0, t1] = cv._view;
        seek(t0 + ((ev.clientX - r.left) / r.width) * (t1 - t0));
      };
      at(e);
      cv.setPointerCapture(e.pointerId);
      cv.onpointermove = (m) => m.buttons && at(m);
    });
    addEventListener(
      "keydown",
      (e) => {
        if (e.target.closest?.("input[type=number],input[type=text],select,textarea,[contenteditable]")) return;
        const k = e.key.toLowerCase(), z = (e.ctrlKey || e.metaKey) && k === "z";
        const act = z ? "undo" : { " ": "play", r: "rec", m: "mute", s: "solo", home: "home" }[k];
        if (!act || ((e.ctrlKey || e.metaKey || e.altKey) && !z)) return;
        e.preventDefault();
        e.stopPropagation();
        A[act]();
        sync();
      },
      true,
    );
  }
  setInterval(ensure, 400);
  ensure();
  requestAnimationFrame(frame);
}
if (variant in NAMES) start();
