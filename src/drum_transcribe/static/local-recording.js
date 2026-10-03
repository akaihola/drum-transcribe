import { LocalTrack, CapturePassage } from "./recording-core.js";
import { loadTrack, saveTrack, clearTrack, peaks } from "./recording-store.js";
import { BeatGrid } from "./recording-grid.js";
let context, contextReady, active;
const ICON = {
  home: '<svg viewBox="0 0 24 24"><path d="M5 4h2.6v16H5zM20 4.5v15L9 12z"/></svg>',
  play: '<svg viewBox="0 0 24 24"><path d="M7 4.5v15l12-7.5z"/></svg>',
  pause: '<svg viewBox="0 0 24 24"><path d="M6 4h4.2v16H6zM13.8 4H18v16h-4.2z"/></svg>',
  record: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="7"/></svg>',
  undo: '<svg viewBox="0 0 24 24"><path d="M9 7.5H4.5V3M5 8a8 8 0 1 1-.9 5" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/></svg>',
  more: '<svg viewBox="0 0 24 24"><circle cx="5" cy="12" r="2"/><circle cx="12" cy="12" r="2"/><circle cx="19" cy="12" r="2"/></svg>',
};
const label = (key) =>
  ({ src: "Original", drumless: "Without drums", drums: "Drums stem" })[key] ??
  `${key} sonification`;
const toDb = (gain) => (gain > 0 ? Math.max(-60, 20 * Math.log10(gain)) : -60);
const fromDb = (db) => (db <= -60 ? 0 : 10 ** (db / 20));
const dbText = (db) =>
  db <= -60
    ? "−∞ dB"
    : `${db > 0 ? "+" : db < 0 ? "−" : ""}${Math.abs(db).toFixed(1)} dB`;
const clock = (t, tenths = true) => {
  const s = Math.max(0, t);
  return `${Math.floor(s / 60)}:${(tenths ? (s % 60).toFixed(1).padStart(4, "0") : String(Math.floor(s % 60)).padStart(2, "0"))}`;
};
const envelopes = new WeakMap();
// Backing waveform: loudest sample per 5 ms, computed once per decoded file.
function envelope(buffer) {
  let e = envelopes.get(buffer);
  if (e) return e;
  const step = Math.round(buffer.sampleRate / 200);
  e = new Float32Array(Math.ceil(buffer.length / step));
  for (let c = 0; c < buffer.numberOfChannels; c++) {
    const data = buffer.getChannelData(c);
    for (let i = 0; i < data.length; i++) {
      const k = (i / step) | 0,
        v = Math.abs(data[i]);
      if (v > e[k]) e[k] = v;
    }
  }
  envelopes.set(buffer, e);
  return e;
}
// Sizes a canvas for its CSS box; returns its context and CSS size.
function fit(canvas) {
  const w = canvas.clientWidth,
    h = canvas.clientHeight,
    d = devicePixelRatio;
  if (canvas.width !== Math.round(w * d) || canvas.height !== Math.round(h * d)) {
    canvas.width = Math.round(w * d);
    canvas.height = Math.round(h * d);
  }
  const g = canvas.getContext("2d");
  g.setTransform(d, 0, 0, d, 0, 0);
  return [g, w, h];
}
async function fingerprint(bytes) {
  return (
    "sha256:" +
    [...new Uint8Array(await crypto.subtle.digest("SHA-256", bytes))]
      .map((b) => b.toString(16).padStart(2, "0"))
      .join("")
  );
}
// Latency correction in ms: one setting per browser, because it belongs to
// the headphones and microphone, not to a song.
const latencyMs = () => +(localStorage.latency ?? 60);
const MEDIA = "audio, yt-audio, practice-audio";
class PracticeAudio extends HTMLElement {
  connectedCallback() {
    if (this.firstChild) return;
    this.innerHTML = `<button type="button" aria-pressed="false">Use as backing</button>`;
    this.querySelector("button").onclick = () =>
      this.owner.requestBacking(this.dataset.backing);
  }
  get paused() {
    return !this.owner?.playing || this.owner.selected !== this.dataset.backing;
  }
  get readyState() {
    return this.owner?.track ? 4 : 0;
  }
  get currentTime() {
    return Math.max(0, this.owner?.current() ?? 0);
  }
  set currentTime(value) {
    this.owner.run(() => this.owner.seek(value));
  }
  set volume(value) {
    this.owner?.setMaster(+value);
  }
  get volume() {
    return this.owner?.bus?.gain.value ?? 1;
  }
  play() {
    return this.owner.requestBacking(this.dataset.backing, true);
  }
  pause() {
    if (!this.paused) return this.owner.requestPause();
  }
  update() {
    const pending = this.owner.pendingBacking,
      on = (pending?.key ?? this.owner.selected) === this.dataset.backing,
      loading = on && !!pending,
      button = this.querySelector("button");
    this.classList.toggle("on", on);
    button.setAttribute("aria-pressed", on);
    button.setAttribute("aria-busy", loading);
    button.textContent = loading ? "Loading…" : on ? "Backing" : "Use as backing";
  }
}
customElements.define("practice-audio", PracticeAudio);
async function audioContext() {
  if (!context) {
    context = new AudioContext({
      latencyHint: "interactive",
      sampleRate: 48000,
    });
    contextReady = context.audioWorklet.addModule(
      "/static/recording-worklet.js",
    );
  }
  const resumed = context.resume();
  await contextReady;
  await resumed;
  return context;
}
export class Recording {
  constructor(section, version, project) {
    section.recording = this;
    this.section = section;
    this.version = version;
    this.project = project;
    this.mode = "playback";
    this.position = 0;
    this.playing = false;
    this.sources = [];
    this.inputGain = 1;
    this.backingGain = 1;
    this.trackGain = 1;
    this.solo = false;
    this.key = `${project}/${version.name}`;
    this.epoch = 0;
    this.cleared = true;
    this.writes = Promise.resolve();
    this.supported = isSecureContext && !!window.AudioWorkletNode;
    this.selected = "src";
    this.zoom = "song";
    this.waveVersion = 0;
    this.bindPlayers();
    this.mount();
    if (this.section.closest(".tabpanel").classList.contains("active"))
      this.loadMetadata();
  }
  backingFiles() {
    return {
      src: this.version.source,
      drums: this.version.drums,
      drumless: this.version.drumless,
      ...Object.fromEntries(
        this.version.variants.map((v) => [v.name, v.files["sonification.ogg"]]),
      ),
    };
  }
  bindPlayers() {
    if (!this.supported) return;
    for (const [key, url] of Object.entries(this.backingFiles())) {
      const node = this.section.querySelector(`[data-piece="${key}"]`);
      const old = node?.querySelector(MEDIA);
      if (!old || !url) continue;
      if (old.tagName === "PRACTICE-AUDIO") {
        old.owner = this;
        continue;
      }
      old.pause();
      const player = document.createElement("practice-audio");
      player.dataset.backing = key;
      player.owner = this;
      old.replaceWith(player);
    }
  }
  update(version) {
    if (this.version.progress.sig !== version.progress.sig) {
      this.backingInvalidated = true;
      this.gridUrl = null;
    }
    if (this.version.sourceIdentity !== version.sourceIdentity && this.track) {
      this.run(async () => {
        const r = await fetch(version.source);
        if (!r.ok) throw Error("The updated source could not be checked.");
        const identity = await fingerprint(await r.arrayBuffer());
        if (identity !== this.sourceIdentity) {
          this.sourceChanged = true;
          this.needsSourceReload = true;
          this.abortCapture("");
          await this.pause();
          this.disarm();
          this.sync();
          this.status(
            "The backing source changed. Your prior recording is preserved. Reload to use the new song length.",
          );
        }
      });
    }
    this.version = version;
    this.bindPlayers();
    this.loadGrid();
    this.sync();
  }
  loadGrid() {
    const url = this.version.beats;
    if (!url || this.gridUrl === url) return;
    this.gridUrl = url;
    fetch(url)
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((beats) => {
        this.grid = new BeatGrid(beats);
        this.sync();
      })
      .catch(() => (this.gridUrl = null));
  }
  loadMetadata() {
    this.loadGrid();
    if (!this.supported || this.metadataRequested || this.track) return;
    this.metadataRequested = true;
    // Show saved takes before audio starts; restore() loads them for editing.
    loadTrack(this.key)
      .then((saved) => {
        if (!saved || this.track) return;
        this.preview = saved;
        this.duration ??= saved.length / saved.rate;
        this.waveVersion++;
      })
      .catch(() => {});
    const audio = (this.metadata = new Audio(this.version.source));
    audio.preload = "metadata";
    const release = () => {
      audio.removeAttribute("src");
      audio.load();
      this.metadata = null;
    };
    audio.onloadedmetadata = () => {
      if (!this.track && Number.isFinite(audio.duration)) {
        this.duration = audio.duration;
        this.sync();
      }
      audio.onloadedmetadata = null;
      release();
    };
    audio.onerror = () => {
      audio.onerror = null;
      release();
    };
  }
  requestSeek(position) {
    this.seekWanted = position;
    if (this.seekQueued) return;
    this.seekQueued = true;
    this.run(async () => {
      try {
        await this.ready();
        const position = this.seekWanted;
        this.seekQueued = false;
        await this.seek(position);
      } finally {
        this.seekQueued = false;
      }
    });
  }
  setMaster(value) {
    if (this.bus) this.bus.gain.value = value;
  }
  mount() {
    const fader = (key, min, max, name) =>
      `<input type="range" data-control="${key}" min="${min}" max="${max}" step="0.5" aria-label="${name}"><output data-db="${key}"></output>`;
    this.ui = document.createElement("div");
    this.ui.className = "local-recording";
    this.ui.innerHTML = `<div class="rec-bar">
      <button class="rec-key" data-action="home" title="Back to start (Home)" aria-label="Back to start">${ICON.home}</button>
      <button class="rec-key play" data-action="play" title="Play / pause (Space)" aria-label="Play">${ICON.play}</button>
      <button class="rec-key rec" data-action="record" title="Record (R)" aria-label="Record" aria-pressed="false">${ICON.record}</button>
      <div class="rec-count"><b data-bar>–</b><span data-time></span></div>
      <button class="rec-key" data-action="undo" title="Undo last passage (Ctrl+Z)" aria-label="Undo last passage" disabled>${ICON.undo}</button>
      <div class="rec-view"><button data-view="song">Whole song</button><button data-view="follow">Follow 16 bars</button></div>
      <output data-status role="status"></output>
      <output data-storage></output>
      <button class="rec-key" data-action="menu" title="Export, import, latency, clear" aria-label="More" aria-expanded="false">${ICON.more}</button>
      <div class="rec-menu" data-menu hidden>
        <button data-action="download"><b>Export WAV</b><span data-heard></span></button>
        <button data-action="import"><b>Import audio…</b><span>Replaces your track, starting at 0:00</span></button>
        <label><b>Latency correction</b><span><input data-control="offset" type="number" min="0" max="1000"> ms earlier — moves all your takes. Play one back and adjust until your hits sit with the backing.</span><output data-estimates></output></label>
        <button data-action="clear" class="danger"><b>Clear your track…</b><span>Removes this version's recording from this browser</span></button>
      </div>
      <input data-import type="file" accept="audio/*,.wav,.flac,.ogg,.mp3,.m4a" hidden>
    </div>
    <div class="rec-grid">
      <div class="rec-head ruler">bars</div><canvas data-draw="ruler"></canvas>
      <div class="rec-head"><b>Backing</b>
        <select data-control="backing" aria-label="Backing"></select>
        <label class="rec-fader">${fader("backingGain", -60, 6, "Backing level")}</label>
        <span class="rec-meter" data-meter="backing"><i></i></span>
      </div><canvas data-draw="backing"></canvas>
      <div class="rec-head you"><b>Your drums <span>
        <button class="rec-t rec" data-action="record" title="Record (R)" aria-label="Record" aria-pressed="false">${ICON.record}</button><button class="rec-t" data-action="mute" title="Mute (M)" aria-pressed="false">M</button><button class="rec-t" data-action="solo" title="Solo (S)" aria-pressed="false">S</button></span></b>
        <label class="rec-fader">${fader("trackGain", -60, 6, "Your track level")}</label>
        <label class="rec-fader"><span>mic</span>${fader("inputGain", -30, 12, "Microphone gain")}<button class="rec-clip" data-action="clip" title="The microphone clipped. Lower the mic gain; click to reset.">CLIP</button></label>
        <span class="rec-meter" data-meter="mic"><i></i></span>
      </div><canvas data-draw="track"></canvas>
    </div>`;
    this.section.querySelector(".flow").after(this.ui);
    this.ui.onclick = (e) => {
      const button = e.target.closest("[data-action], [data-view]");
      if (!button) return;
      if (button.dataset.view) {
        this.zoom = button.dataset.view;
        this.view = null;
        this.sync();
      } else this.act(button.dataset.action);
    };
    this.ui.oninput = (e) => {
      const key = e.target.dataset.control;
      // A select fires input before change. Keep its new value until the
      // change handler requests it, rather than syncing the previous backing.
      if (key === "backing") return;
      if (key === "inputGain") {
        this.inputGain = fromDb(+e.target.value);
        if (this.inputLevel) this.inputLevel.gain.value = this.inputGain;
      } else if (key === "backingGain" || key === "trackGain") {
        this[key] = fromDb(+e.target.value);
        this.balance();
      } else if (key === "offset") {
        localStorage.latency = Math.max(0, Math.min(1000, +e.target.value || 0));
        this.align();
      }
      this.sync();
    };
    this.ui.onchange = (e) => {
      const key = e.target.dataset.control;
      if (key === "backing")
        this.requestBacking(e.target.value);
    };
    this.ui.querySelector("[data-import]").onchange = (e) => {
      const file = e.target.files[0];
      if (file) this.run(() => this.importAudio(file));
      e.target.value = "";
    };
    // Mouse: press or drag to seek. Touch: tap or drag sideways to seek,
    // pinch with two fingers to zoom the time axis around them (moving
    // them pans); vertical swipes are left to the page (touch-action).
    // The lanes share one time axis, so fingers may land on different ones.
    const touches = new Map(); // pointerId -> clientX
    let gesture, pinch;
    const at = (canvas, clientX) => {
      const r = canvas.getBoundingClientRect(),
        [t0, t1] = this.shown ?? [];
      return t1 > t0 ? t0 + ((clientX - r.left) / r.width) * (t1 - t0) : null;
    };
    const seek = (canvas, clientX) => {
      const t = at(canvas, clientX);
      if (t !== null) this.requestSeek(t);
    };
    const zoom = ([a, b]) => {
      const d = this.duration,
        r = pinch.canvas.getBoundingClientRect(),
        span = Math.min(d, Math.max(2, (pinch.span * pinch.gap) / (Math.abs(a - b) || 1))),
        start = Math.max(0, Math.min(d - span,
          pinch.anchor - (((a + b) / 2 - r.left) / r.width) * span));
      this.view = span < d ? [start, start + span] : null; // fully out: whole song
      this.viewAt = this.current();
      this.draw();
    };
    for (const canvas of this.ui.querySelectorAll("canvas")) {
      canvas.onpointerdown = (e) => {
        if (e.pointerType === "mouse") {
          canvas.setPointerCapture(e.pointerId);
          return seek(canvas, e.clientX);
        }
        touches.set(e.pointerId, e.clientX);
        if (touches.size === 1) gesture = { x: e.clientX, scrub: false, multi: false };
        else if (touches.size === 2 && this.shown) {
          const [a, b] = touches.values();
          gesture.multi = true;
          pinch = { canvas, gap: Math.abs(a - b) || 1, span: this.shown[1] - this.shown[0],
                    anchor: at(canvas, (a + b) / 2) };
        }
      };
      canvas.onpointermove = (e) => {
        if (e.pointerType === "mouse") return e.buttons && seek(canvas, e.clientX);
        if (!touches.has(e.pointerId)) return;
        touches.set(e.pointerId, e.clientX);
        if (pinch && touches.size === 2) return zoom([...touches.values()]);
        if (gesture.multi) return;
        gesture.scrub ||= Math.abs(e.clientX - gesture.x) > 8;
        if (gesture.scrub) seek(canvas, e.clientX);
      };
      canvas.onpointerup = (e) => {
        if (e.pointerType === "mouse" || !touches.delete(e.pointerId)) return;
        if (touches.size < 2) pinch = null;
        if (!touches.size && !gesture.multi && !gesture.scrub) seek(canvas, e.clientX);
      };
      canvas.onpointercancel = (e) => {
        touches.delete(e.pointerId); // the page scrolled instead
        if (gesture) gesture.multi = true;
        if (touches.size < 2) pinch = null;
      };
    }
    document.addEventListener("click", (e) => {
      if (!e.target.closest(".rec-menu, [data-action=menu]")) this.menu(false);
    });
    this.resize = new ResizeObserver(() => this.draw());
    this.resize.observe(this.ui);
    window.addEventListener("pagehide", () => {
      this.abortCapture("");
      this.stopSources();
      this.playing = false;
      this.disarm();
      clearTimeout(this.auditionTimer);
      this.persist();
      this.writes.finally(() => this.unlock?.()).catch(() => {});
      this.writable = false;
    });
    if (!this.supported)
      this.ui
        .querySelectorAll("button,input,select")
        .forEach((control) => (control.disabled = true));
    window.addEventListener("pageshow", (e) => {
      if (e.persisted)
        this.status(
          "Reload this page to reopen the local recording for editing.",
        );
    });
    this.sync();
    this.timer = setInterval(() => this.tick(), 50);
  }
  act(action) {
    this.messageUntil = 0; // a new action makes the last message stale
    const actions = {
      home: () => this.requestSeek(0),
      play: () => (this.playing ? this.requestPause() : this.run(() => this.play())),
      record: () =>
        this.run(() =>
          this.setMode(this.mode === "record" ? "playback" : "record"),
        ),
      mute: () =>
        this.run(() => this.setMode(this.mode === "mute" ? "playback" : "mute")),
      solo: () => {
        this.solo = !this.solo;
        this.balance();
      },
      undo: () =>
        this.track?.undo &&
        this.run(async () => {
          await this.ready();
          this.requireWriter();
          await this.pause();
          this.track.undoLast();
          this.edited();
        }),
      menu: () => this.menu(this.ui.querySelector("[data-menu]").hidden),
      download: () => this.run(() => this.download()),
      import: () => this.ui.querySelector("[data-import]").click(),
      clear: () => {
        if (
          !confirm(
            "Clear your recording of this version? Export a WAV first if you want to keep it.",
          )
        )
          return;
        this.epoch++;
        this.clear().catch((e) => this.status(e.message));
      },
      clip: () => (this.clipped = false),
    };
    if (action !== "menu" && action !== "import") this.menu(false);
    actions[action]?.();
    this.sync();
  }
  menu(open) {
    this.ui.querySelector("[data-menu]").hidden = !open;
    this.ui
      .querySelector("[data-action=menu]")
      .setAttribute("aria-expanded", open);
  }
  storageMessage(message) {
    this.ui.querySelector("[data-storage]").textContent = message;
  }
  // Messages show for a while; otherwise the line says what Play will do.
  status(message) {
    this.message = message;
    this.messageUntil = message ? performance.now() + 8000 : 0;
    this.showStatus();
  }
  showStatus() {
    const text = this.pendingBacking
      ? this.pendingBacking.message +
        (this.playing && this.backingLevel() > 0
          ? ` Still hearing ${label(this.selected)}.`
          : "")
      : performance.now() < this.messageUntil
        ? this.message
        : this.liveStatus();
    const el = this.ui.querySelector("[data-status]");
    if (el.textContent !== text) el.textContent = text;
  }
  liveStatus() {
    if (!this.supported)
      return "Recording needs HTTPS or localhost. The players above still work.";
    if (this.sourceChanged)
      return "The song file changed. Your track is kept: listen with Solo, export it, then Clear to start over.";
    if (this.writable === false)
      return "Another tab is editing this version. Close it and reload this page to record.";
    const at = (t) =>
      !this.grid
        ? clock(t)
        : this.grid.barAt(t).bar < 1
          ? "the start"
          : `bar ${this.grid.barAt(t).bar}`;
    if (this.mode === "record") {
      if (!this.playing)
        return `Armed — press Play (Space) to record from ${at(this.position)}${this.grid ? " after a two-bar lead-in" : ""}`;
      const start = (this.passage?.start ?? 0) / this.track.rate,
        now = this.current();
      if (now < start)
        return `${now < 0 ? "Count-in" : "Pre-roll"} — recording starts at ${at(start)}`;
      return `Recording since ${at(start)} — only what the playhead crosses is replaced`;
    }
    if (this.mode === "mute")
      return `Your track is muted · hearing ${label(this.selected)}`;
    if (this.solo) return "Your track solo";
    return (this.track ?? this.preview)?.segments.length
      ? `Hearing ${label(this.selected)} + your track`
      : `Hearing ${label(this.selected)} · press Record (R) to start your track`;
  }
  run(fn) {
    const epoch = this.epoch;
    this.queue = (this.queue ?? Promise.resolve()).then(async () => {
      if (epoch !== this.epoch) return;
      this.runningEpoch = epoch;
      try {
        await fn();
      } catch (e) {
        if (epoch !== this.epoch) return;
        await this.pause();
        this.status(e.message);
        this.disarm();
        this.sync();
      } finally {
        this.runningEpoch = null;
      }
    });
    return this.queue;
  }
  async ready() {
    if (!this.supported)
      throw Error(
        "Local recording needs HTTPS or localhost and AudioWorklet support.",
      );
    if (this.track && this.bus) {
      this.ctx = await audioContext();
      if (this.needsSourceReload && !this.track.segments.length)
        await this.reloadSource();
      this.align(); // the setting may have changed on another version's tab
      return;
    }
    if (!this.loading)
      this.loading = this.initialize().finally(() => (this.loading = null));
    return this.loading;
  }
  async initialize() {
    const epoch = this.epoch;
    this.ctx = await audioContext();
    if (!this.track) {
      const r = await fetch(this.version.source);
      if (!r.ok) throw Error("Backing could not be loaded. Try again.");
      this.backingKey = "src";
      const encoded = await r.arrayBuffer();
      this.sourceIdentity = await fingerprint(encoded);
      this.backing = await this.ctx.decodeAudioData(encoded);
      this.track = new LocalTrack(this.ctx.sampleRate, this.backing.length);
      this.sourceFrames = this.backing.length;
      this.duration = this.backing.duration;
      this.needsSourceReload = false;
      await this.restore(epoch);
      this.bus = this.ctx.createGain();
      this.bus.gain.value = +(localStorage.volume ?? 1);
      // Listening and export use the same hard peak limit, before master volume.
      this.clip = this.ctx.createWaveShaper();
      this.clip.curve = new Float32Array([-1, 1]);
      this.clip.connect(this.bus);
      this.bus.connect(this.ctx.destination);
      this.backingBus = this.ctx.createGain();
      this.backingBus.connect(this.clip);
      this.backingMeter = this.ctx.createAnalyser();
      this.backingMeter.fftSize = 2048;
      this.backingBus.connect(this.backingMeter);
      this.ctx.addEventListener("statechange", () => {
        if (this.ctx.state !== "running" && this.playing) {
          this.abortCapture(
            "Audio interrupted. The unfinished passage was kept.",
          );
          this.pause();
          this.disarm();
          this.sync();
        }
      });
    }
  }
  acquireWriter() {
    if (!this.lockReady)
      this.lockReady = new Promise((resolve) => {
        if (!navigator.locks) {
          this.writable = false;
          resolve();
          return;
        }
        navigator.locks
          .request(
            `drum-recording:${this.key}`,
            { ifAvailable: true },
            (lock) => {
              this.writable = !!lock;
              resolve();
              if (lock)
                return new Promise((release) => (this.unlock = release));
            },
          )
          .catch((e) => {
            this.status(e.message);
            this.writable = false;
            resolve();
          });
      });
    return this.lockReady;
  }
  async restore(epoch = this.epoch) {
    await this.acquireWriter();
    if (epoch !== this.epoch) return;
    try {
      const saved = await loadTrack(this.key);
      if (epoch !== this.epoch) return;
      this.preview = null;
      if (saved) {
        this.cleared = false;
        if (saved.rate !== this.track.rate)
          throw Error(
            "Saved audio uses a different sample rate. Open it with the original audio settings.",
          );
        this.track.segments = saved.segments;
        this.align();
        this.audition = saved.audition;
        if (this.audition && this.backingFiles()[this.audition.backing])
          this.selected = this.audition.backing;
        this.sourceChanged =
          saved.sourceIdentity !== this.sourceIdentity ||
          saved.length !== this.track.length;
        if (this.sourceChanged) {
          this.track.length = saved.length;
          this.duration = saved.length / this.track.rate;
        }
        if (this.audition) {
          this.backingGain = this.audition.backingGain;
          this.trackGain = this.audition.trackGain;
          this.solo = this.audition.solo;
        }
        this.storageMessage("Recording restored from browser storage.");
        this.status(
          this.sourceChanged
            ? "The backing source changed. Download your take, then Clear to start over."
            : "Recording restored from this browser.",
        );
      }
    } catch (e) {
      if (epoch !== this.epoch) return;
      this.storageUnavailable = true;
      this.restoreFailed = true;
      this.storageMessage(
        "Browser storage unavailable. New takes stay in memory. Download before closing.",
      );
      this.status(
        `Browser storage unavailable: ${e.message}. New takes stay in memory; download them before closing.`,
      );
    }
    if (!this.writable)
      this.status(
        "Another tab is editing this version, or this browser has no track locks. Listening is available. Close the other tab and reload to record.",
      );
    this.waveVersion++;
    this.sync();
  }
  requireWriter(allowChanged = false) {
    if (!this.writable)
      throw Error(
        "This version is open for editing in another tab. Close that tab and reload.",
      );
    if (this.sourceChanged && !allowChanged)
      throw Error(
        "Backing source changed. Download your take and Clear before recording.",
      );
  }
  persist() {
    if (!this.track || !this.writable || this.sourceChanged || this.cleared)
      return;
    if (this.restoreFailed) {
      this.storageMessage(
        "Saved data could not be read. New takes stay in memory. Download before closing, or Clear to reset storage.",
      );
      return;
    }
    this.storageMessage("Saving in this browser...");
    const epoch = this.epoch,
      segments = this.track.segments;
    const state = {
      rate: this.track.rate,
      length: this.track.length,
      sourceIdentity: this.sourceIdentity,
      audition: this.audition,
    };
    this.writes = this.writes
      .catch(() => {})
      .then(async () => {
        if (epoch !== this.epoch) return;
        await saveTrack(this.key, state, segments);
        if (epoch === this.epoch) {
          this.storageMessage("✓ saved in this browser");
        }
      })
      .catch((e) => {
        if (epoch === this.epoch) {
          this.storageMessage("Only in memory. Download before closing.");
          this.status(
            `Not saved: ${e.message}. Your take is still in memory. Download it before closing.`,
          );
        }
      });
    return this.writes;
  }
  latency() {
    return Math.round((latencyMs() * this.track.rate) / 1000);
  }
  // Moves microphone takes to the current latency correction, audibly at once.
  align() {
    if (!this.track?.realign(this.latency())) return;
    this.waveVersion++;
    if (this.playing) this.schedule();
  }
  edited() {
    this.cleared = false;
    for (const s of this.track.segments) peaks(s.data);
    this.waveVersion++;
    this.persist();
    this.sync();
  }
  cancelExport() {
    this.exportWorker?.terminate();
    this.exportWorker = null;
    this.exportReject?.(
      Error("Download cancelled because the track was cleared."),
    );
    this.exportReject = null;
    if (this.downloadUrl) URL.revokeObjectURL(this.downloadUrl);
    this.downloadUrl = null;
  }
  async createWav() {
    const epoch = this.runningEpoch ?? this.epoch;
    await this.ready();
    await this.pause();
    if (epoch !== this.epoch) throw Error("Download cancelled.");
    const mix = this.audition ?? { backingGain: 0, trackGain: 1, solo: true };
    let backing = null;
    if (!mix.solo && mix.backingGain > 0) {
      if (this.sourceChanged)
        throw Error(
          "The backing source changed. Your remembered mix cannot be reproduced. Listen with Solo enabled, then download to save your recording alone.",
        );
      const url = this.backingFiles()[mix.backing];
      if (!url)
        throw Error(
          "The remembered backing is unavailable. Try again after processing finishes.",
        );
      if (this.backingKey === mix.backing) backing = this.backing;
      else {
        const r = await fetch(url);
        if (!r.ok) throw Error("The remembered backing could not be loaded.");
        const bytes = await r.arrayBuffer();
        this.backing = null;
        this.backingKey = null;
        backing = await this.ctx.decodeAudioData(bytes);
        this.backing = backing;
        this.backingKey = mix.backing;
      }
    }
    if (epoch !== this.epoch) throw Error("Download cancelled.");
    const track = this.track;
    const channels = Math.max(
      backing?.numberOfChannels ?? 1,
      ...track.segments.map((s) => s.data.channels.length),
      1,
    );
    return new Promise((resolve, reject) => {
      const worker = (this.exportWorker = new Worker(
        "/static/recording-export.js",
        { type: "module" },
      ));
      this.exportReject = reject;
      const finish = () => {
        worker.terminate();
        this.exportWorker = null;
        this.exportReject = null;
      };
      worker.onerror = (e) => {
        finish();
        reject(
          Error(e.message || "WAV encoding failed. Your recording is safe."),
        );
      };
      worker.onmessage = ({ data }) => {
        if (epoch !== this.epoch) {
          finish();
          reject(Error("Download cancelled."));
          return;
        }
        if (data.type === "done") {
          finish();
          resolve(data.blob);
        } else if (data.type === "error") {
          finish();
          reject(Error(data.message));
        } else if (data.type === "need") {
          const recording = [],
            original = [];
          for (let c = 0; c < channels; c++) {
            recording.push(track.read(data.frame, data.size, c));
            original.push(
              backing
                ? backing
                    .getChannelData(Math.min(c, backing.numberOfChannels - 1))
                    .slice(data.frame, data.frame + data.size)
                : new Float32Array(0),
            );
          }
          worker.postMessage(
            { type: "block", recording, backing: original },
            [...recording, ...original].map((a) => a.buffer),
          );
          this.status(
            `Preparing whole-song WAV: ${Math.round((data.frame / track.length) * 100)}%.`,
          );
        }
      };
      worker.postMessage({
        type: "start",
        rate: track.rate,
        length: track.length,
        channels,
        backingGain: mix.solo ? 0 : mix.backingGain,
        trackGain: mix.trackGain,
      });
    });
  }
  async download() {
    const blob = await this.createWav();
    if (this.downloadUrl) URL.revokeObjectURL(this.downloadUrl);
    this.downloadUrl = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = this.downloadUrl;
    link.download = `${this.project}-${this.version.name}-local-recording.wav`;
    link.click();
    this.status(
      "Whole-song WAV downloaded using the last heard recording mix, or solo before any audition.",
    );
  }
  async importAudio(file) {
    const epoch = this.runningEpoch ?? this.epoch;
    await this.ready();
    this.requireWriter();
    const buffer = await this.ctx.decodeAudioData(await file.arrayBuffer());
    if (buffer.length > this.track.length)
      throw Error(
        `This audio is longer than the ${this.duration.toFixed(2)} second song. Import a file that fits; nothing was changed.`,
      );
    if (buffer.numberOfChannels > 2)
      throw Error("Import mono or stereo audio. Nothing was changed.");
    const segments = [],
      take = crypto.randomUUID();
    for (let start = 0; start < buffer.length; start += 65536) {
      const end = Math.min(buffer.length, start + 65536),
        channels = [];
      for (let c = 0; c < buffer.numberOfChannels; c++) {
        const data = buffer.getChannelData(c).slice(start, end);
        if (!data.every(Number.isFinite))
          throw Error(
            "This audio contains invalid samples. Nothing was changed.",
          );
        channels.push(data);
      }
      segments.push({
        start,
        end,
        offset: 0,
        take,
        data: { id: `${take}-${start}`, channels },
      });
    }
    if (epoch !== this.epoch) return;
    await this.pause();
    if (epoch !== this.epoch) return;
    this.disarm();
    this.track.replace(0, this.track.length, segments);
    this.edited();
    this.status(
      "Audio imported at song time zero. Solo hears any backing already mixed into the file.",
    );
  }
  async reloadSource() {
    const response = await fetch(this.version.source);
    if (!response.ok)
      throw Error(
        "The changed source could not be loaded. Your local track is clear. Try again.",
      );
    const bytes = await response.arrayBuffer(),
      identity = await fingerprint(bytes);
    const backing = await this.ctx.decodeAudioData(bytes);
    this.backing = backing;
    this.backingKey = this.selected = "src";
    this.backingInvalidated = false;
    this.sourceIdentity = identity;
    this.sourceFrames = this.track.length = backing.length;
    this.duration = backing.duration;
    this.needsSourceReload = false;
  }
  async clear() {
    await this.acquireWriter();
    this.requireWriter(true);
    const reload = this.needsSourceReload || this.sourceChanged;
    this.epoch++;
    this.cancelBacking();
    clearTimeout(this.auditionTimer);
    this.cancelExport();
    this.abortCapture("");
    this.position = Math.max(this.current(), this.recordFrom ?? 0);
    this.recordFrom = null;
    this.playing = false;
    this.stopSources();
    this.disarm();
    this.cleared = true;
    if (this.track) {
      this.track.clear();
      this.track.length = this.sourceFrames;
      this.duration = this.sourceFrames / this.track.rate;
    }
    this.audition = this.preview = null;
    this.sourceChanged = false;
    this.waveImage = null;
    this.backingGain = this.trackGain = 1;
    this.solo = false;
    this.waveVersion++;
    this.sync();
    this.writes = this.writes.catch(() => {}).then(() => clearTrack(this.key));
    try {
      await this.writes;
      this.restoreFailed = false;
      this.storageMessage("");
      this.status("Local recording and remembered mix cleared.");
    } catch (e) {
      this.storageMessage(
        "Browser storage could not be cleared. Retry Clear before closing.",
      );
      this.status(
        `Memory cleared, but browser storage could not be cleared: ${e.message}. Retry Clear before closing.`,
      );
    }
    if (reload) {
      this.needsSourceReload = true;
      try {
        await this.reloadSource();
        this.sync();
      } catch (e) {
        this.status(e.message);
      }
    }
  }
  disarm() {
    if (this.mode === "record") this.mode = "playback";
    this.releaseMic();
  }
  releaseMic() {
    if (this.stream)
      for (const t of this.stream.getTracks()) {
        t.onended = t.onmute = null;
        t.stop();
      }
    this.input?.disconnect();
    this.capture?.disconnect();
    this.analyser?.disconnect();
    this.inputLevel?.disconnect();
    this.stream =
      this.input =
      this.capture =
      this.analyser =
      this.inputLevel =
        null;
  }
  shownRange() {
    const d = this.duration ?? 0;
    if (this.view) {
      // A pinched window pages along with playback and seeks, but stays
      // where the fingers left it while the playhead stands still.
      const [t0, t1] = this.view,
        span = t1 - t0,
        t = this.current();
      if ((this.playing || t !== this.viewAt) && (t < t0 || t > t1)) {
        const start = Math.max(0, Math.min(d - span, t - span / 10));
        this.view = [start, start + span];
      }
      this.viewAt = t;
      return this.view;
    }
    if (this.zoom !== "follow" || !this.grid) return [0, d];
    const { bar } = this.grid.barAt(Math.max(0, this.current())),
      t0 = Math.max(0, this.grid.barStart(bar - 2)),
      t1 = Math.min(d, this.grid.barStart(bar + 14));
    return t1 > t0 ? [t0, t1] : [0, d];
  }
  // Recorded passages: runs of segments from one take or import.
  takes() {
    const out = [];
    for (const s of (this.track ?? this.preview)?.segments ?? []) {
      const id = s.take ?? s.data.id.replace(/-\d+$/, ""),
        last = out.at(-1);
      if (last?.id === id && last.end === s.start) {
        last.end = s.end;
        last.segments.push(s);
      } else out.push({ id, start: s.start, end: s.end, segments: [s] });
    }
    return out;
  }
  draw() {
    if (!this.ui.offsetWidth) return;
    if (!this.duration) {
      const [g, w, h] = fit(this.ui.querySelector('[data-draw="backing"]'));
      g.clearRect(0, 0, w, h);
      g.font = "11px 'Alegreya Sans', sans-serif";
      g.textBaseline = "top";
      this.drawBacking(g, null, 0, 0, w, h);
      return;
    }
    const [t0, t1] = (this.shown = this.shownRange()),
      muted = this.mode === "mute",
      key = [t0, t1, this.waveVersion, muted, this.solo, this.mode].join(),
      refs = [
        this.backing, this.backingKey, this.grid, this.pendingBacking?.message,
      ];
    for (const canvas of this.ui.querySelectorAll("canvas")) {
      const [g, w, h] = fit(canvas),
        x = (t) => ((t - t0) / (t1 - t0)) * w,
        kind = canvas.dataset.draw;
      if (!w) continue;
      if (
        canvas.layerKey !== key + w + h ||
        refs.some((r, i) => r !== canvas.layerRefs?.[i])
      ) {
        canvas.layerKey = key + w + h;
        canvas.layerRefs = refs;
        canvas.layer ??= document.createElement("canvas");
        canvas.layer.width = canvas.width;
        canvas.layer.height = canvas.height;
        const l = canvas.layer.getContext("2d");
        l.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0);
        l.font = "11px 'Alegreya Sans', sans-serif";
        l.textBaseline = "top";
        this.drawGrid(l, x, t0, t1, w, h, kind === "ruler");
        if (kind === "backing") this.drawBacking(l, x, t0, t1, w, h);
        if (kind === "track") this.drawTakes(l, x, h, muted);
      }
      g.clearRect(0, 0, w, h);
      g.drawImage(canvas.layer, 0, 0, w, h);
      if (kind === "track" && this.passage)
        this.drawPassage(g, x, h);
      const t = this.current();
      if (t >= t0 && t <= t1) {
        g.fillStyle = this.passage ? "#C40000" : "#232019";
        g.fillRect(Math.round(x(t)), 0, 1.5, h);
      }
    }
  }
  drawGrid(g, x, t0, t1, w, h, labels) {
    if (!this.grid) {
      if (!labels) return;
      const every = [1, 2, 5, 10, 15, 30, 60].find((s) => x(t0 + s) > 50) ?? 120;
      g.fillStyle = "#6E675C";
      for (let t = Math.ceil(t0 / every) * every; t <= t1; t += every) {
        g.fillRect(Math.round(x(t)), 4, 1, h - 4);
        g.fillText(clock(t, false), Math.round(x(t)) + 3, 5);
      }
      return;
    }
    const first = this.grid.barAt(t0).bar,
      last = this.grid.barAt(t1).bar,
      px = x(this.grid.barStart(first + 1)) - x(this.grid.barStart(first)),
      every = [1, 2, 4, 8, 16, 32].find((n) => n * px > 34) ?? 64;
    for (let bar = Math.max(1, first); bar <= last; bar++) {
      const at = Math.round(x(this.grid.barStart(bar))),
        major = bar === 1 || bar % every === 0;
      if (labels) {
        g.fillStyle = major ? "#232019" : "#B9B2A6";
        g.fillRect(at, major ? 4 : h * 0.6, 1, major ? h - 4 : h * 0.4);
        if (major) g.fillText(bar, at + 3, 5);
      } else if (px > 3 || major) {
        g.fillStyle = bar % 4 === 1 ? "rgba(35,32,25,.1)" : "rgba(35,32,25,.04)";
        g.fillRect(at, 0, 1, h);
      }
    }
  }
  drawBacking(g, x, t0, t1, w, h) {
    if (this.pendingBacking || !this.backing || this.backingKey !== this.selected) {
      g.fillStyle = "#6E675C";
      g.fillText(
        this.pendingBacking?.message ?? "The backing waveform appears once it has loaded.",
        8, h / 2 - 6,
      );
      return;
    }
    const e = envelope(this.backing),
      rate = e.length / this.backing.duration;
    g.fillStyle =
      this.solo && this.mode === "playback" ? "#DCD6CA" : "#8C8579";
    for (let px = 0; px < w; px++) {
      const k0 = Math.floor((t0 + (px / w) * (t1 - t0)) * rate),
        k1 = Math.floor((t0 + ((px + 1) / w) * (t1 - t0)) * rate);
      let m = 0;
      for (let k = k0; k <= k1 && k < e.length; k++) m = Math.max(m, e[k]);
      const half = Math.max(0.5, m * (h / 2 - 6));
      g.fillRect(px, h / 2 - half, 1, half * 2);
    }
  }
  drawTakes(g, x, h, muted) {
    const rate = (this.track ?? this.preview)?.rate,
      ink = muted ? "#A9A296" : "#0E7386";
    for (const take of this.takes()) {
      const a = x(take.start / rate),
        b = x(take.end / rate);
      if (b < 0 || a > g.canvas.width) continue;
      g.fillStyle = muted ? "rgba(110,103,92,.1)" : "rgba(14,115,134,.1)";
      g.fillRect(a, 0, b - a, h);
      g.fillStyle = ink;
      g.fillRect(a, 0, b - a, 2);
      const from = take.start / rate,
        to = (take.end - 1) / rate,
        text = this.grid
          ? `bars ${this.grid.barAt(from).bar}–${this.grid.barAt(to).bar}`
          : `${clock(from, false)}–${clock(to, false)}`;
      if (b - a > g.measureText(text).width + 10) g.fillText(text, a + 4, 5);
      this.drawSegments(g, x, h, take.segments, ink);
    }
  }
  drawSegments(g, x, h, segments, ink) {
    const rate = (this.track ?? this.preview).rate,
      mid = h / 2 + 8,
      scale = h / 2 - 12;
    g.fillStyle = ink;
    for (const s of segments) {
      const p = peaks(s.data),
        step = Math.max(1, Math.floor((x(256 / rate) - x(0)) ** -1));
      for (let b = Math.floor(s.offset / 256); b * 256 < s.offset + s.end - s.start; b += step) {
        const t = (s.start + b * 256 - s.offset) / rate;
        if (t < s.start / rate) continue;
        let lo = 0,
          hi = 0;
        for (let k = b; k < b + step && k * 2 + 1 < p.length; k++) {
          lo = Math.min(lo, p[k * 2]);
          hi = Math.max(hi, p[k * 2 + 1]);
        }
        g.fillRect(x(t), mid - hi * scale, 1, Math.max(1, (hi - lo) * scale));
      }
    }
  }
  drawPassage(g, x, h) {
    const rate = this.track.rate,
      start = this.passage.start / rate,
      now = this.current();
    if (now <= start) return;
    g.fillStyle = "rgba(196,0,0,.12)";
    g.fillRect(x(start), 0, x(now) - x(start), h);
    g.fillStyle = "#C40000";
    g.fillRect(x(start), 0, x(now) - x(start), 2);
    this.drawSegments(g, x, h, this.passage.parts, "#C40000");
  }
  cancelBacking() {
    this.pendingBacking?.controller.abort();
    this.pendingBacking = null;
    this.sync();
  }
  beginBacking(key) {
    this.cancelBacking();
    this.messageUntil = 0;
    this.pendingBacking = {
      key,
      controller: new AbortController(),
      message: `Loading ${label(key)}…`,
    };
    this.sync();
    return this.pendingBacking;
  }
  // A requested choice is visible immediately; selected still names the audio
  // actually heard, including the mix remembered for export.
  requestBacking(key, play = false) {
    if (!this.backingFiles()[key]) return Promise.resolve();
    if (this.pendingBacking?.key === key && this.pendingBacking.promise) {
      this.pendingBacking.play ||= play;
      return this.pendingBacking.promise;
    }
    const request = this.beginBacking(key);
    request.play = play;
    return (request.promise = this.run(async () => {
      if (await this.selectBacking(key, request)) {
        if (request.play && !request.controller.signal.aborted) await this.play();
      }
    }));
  }
  async backingBytes(response, request) {
    if (!response.body) return response.arrayBuffer();
    const reader = response.body.getReader(),
      total = +response.headers.get("Content-Length"),
      chunks = [];
    let size = 0;
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      chunks.push(value);
      size += value.length;
      const progress =
        total > 0
          ? `${Math.min(100, Math.floor((size / total) * 100))}%`
          : `${(size / 1048576).toFixed(1)} MB`;
      const message = `Loading ${label(request.key)}… ${progress}`;
      if (message !== request.message) {
        request.message = message;
        if (this.pendingBacking === request) this.sync();
      }
    }
    const bytes = new Uint8Array(size);
    let offset = 0;
    for (const chunk of chunks) {
      bytes.set(chunk, offset);
      offset += chunk.length;
    }
    return bytes.buffer;
  }
  async selectBacking(key, request = this.beginBacking(key)) {
    const epoch = this.runningEpoch ?? this.epoch;
    const stale = () => epoch !== this.epoch || request.controller.signal.aborted;
    let prepared = false;
    try {
      if (stale() || !this.backingFiles()[key]) return false;
      await this.ready();
      if (stale()) return false;
      if (
        this.selected === key && this.backingKey === key &&
        this.backing && !this.backingInvalidated
      )
        return true;
      let buffer = this.backing;
      // initialize() already decoded Original. Reuse it even if restore()
      // remembered a different choice; no second download is needed.
      if (!buffer || this.backingKey !== key || this.backingInvalidated) {
        const response = await fetch(this.backingFiles()[key], {
          signal: request.controller.signal,
        });
        if (!response.ok) throw Error("Backing download failed.");
        const bytes = await this.backingBytes(response, request);
        if (stale()) return false;
        request.message = `Preparing ${label(key)} audio…`;
        this.sync();
        buffer = await this.ctx.decodeAudioData(bytes);
      }
      if (stale()) return false;
      prepared = true;
      if (this.passage) await this.finishCapture();
      if (stale()) {
        // A newer choice can arrive while the capture tail drains. Continue
        // recording the old backing until that choice is ready to replace it.
        if (epoch === this.epoch && this.playing && this.mode === "record")
          this.beginCapture();
        return false;
      }
      this.selected = this.backingKey = key;
      this.backing = buffer;
      this.backingInvalidated = false;
      if (this.playing) {
        this.schedule();
        if (this.mode === "record") this.beginCapture();
        this.rememberAudition();
      }
      return true;
    } catch (e) {
      if (stale()) return false;
      if (prepared) throw e;
      this.status(`${label(key)} could not be loaded. Choose it again to retry.`);
      return false;
    } finally {
      if (this.pendingBacking === request) {
        this.pendingBacking = null;
        this.sync();
      }
    }
  }
  backingLevel() {
    return this.mode === "playback" && this.solo ? 0 : this.backingGain;
  }
  deactivate() {
    this.armingEpoch = (this.armingEpoch ?? 0) + 1;
    this.cancelBacking();
    return this.run(async () => {
      await this.pause();
      this.disarm();
      this.backing = null;
      this.backingKey = null;
      this.sync();
    });
  }
  balance() {
    for (const { gain, local } of this.gains ?? [])
      gain.gain.value = local ? this.trackGain : this.backingLevel();
    this.rememberAudition();
  }
  rememberAudition() {
    if (
      !this.playing ||
      this.current() <= this.position + 0.005 ||
      this.mode !== "playback" ||
      this.trackGain <= 0 ||
      !this.track?.segments.length
    )
      return;
    const audition = {
      backing: this.selected,
      backingGain: this.solo ? 0 : this.backingGain,
      trackGain: this.trackGain,
      solo: this.solo,
    };
    if (JSON.stringify(audition) === JSON.stringify(this.audition)) return;
    this.audition = audition;
    clearTimeout(this.auditionTimer);
    this.auditionTimer = setTimeout(() => this.persist(), 250);
  }
  current() {
    return this.playing
      ? Math.min(
          this.duration,
          Math.max(this.from, this.ctx.currentTime - this.anchor),
        )
      : this.position;
  }
  async microphone() {
    const epoch = this.runningEpoch ?? this.epoch,
      arming = this.armingEpoch;
    if (this.stream?.getAudioTracks()[0]?.readyState === "live") return;
    if (!isSecureContext || !navigator.mediaDevices)
      throw Error(
        "Recording needs HTTPS or localhost. Open this page at a trusted HTTPS address.",
      );
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        echoCancellation: false,
        noiseSuppression: false,
        autoGainControl: false,
      },
    });
    if (epoch !== this.epoch || arming !== this.armingEpoch) {
      stream.getTracks().forEach((t) => t.stop());
      throw Error("Recording was cancelled.");
    }
    this.stream = stream;
    const input = (this.input = this.ctx.createMediaStreamSource(stream));
    this.analyser = this.ctx.createAnalyser();
    this.analyser.fftSize = 2048;
    this.inputLevel = this.ctx.createGain();
    this.inputLevel.gain.value = this.inputGain;
    input.connect(this.inputLevel);
    this.inputLevel.connect(this.analyser);
    this.capture = new AudioWorkletNode(this.ctx, "drum-capture", {
      outputChannelCount: [1],
    });
    this.inputLevel.connect(this.capture);
    this.capture.connect(this.ctx.destination);
    this.capture.port.onmessage = ({ data }) => {
      if (data.id !== this.passage?.id) return;
      if (data.type === "samples") this.passage.add(data);
      if (data.type === "done") this.completeCapture();
    };
    const settings = stream.getAudioTracks()[0].getSettings();
    this.ui.querySelector("[data-estimates]").textContent =
      `Browser estimates, not calibration: base ${Math.round(this.ctx.baseLatency * 1000)} ms, output ${Math.round((this.ctx.outputLatency ?? 0) * 1000)} ms, input ${settings.latency === undefined ? "unknown" : Math.round(settings.latency * 1000) + " ms"}. Speech processing: echo ${settings.echoCancellation ?? "unknown"}, noise ${settings.noiseSuppression ?? "unknown"}, automatic gain ${settings.autoGainControl ?? "unknown"}.`;
    stream.getAudioTracks()[0].onended = stream.getAudioTracks()[0].onmute =
      () => {
        this.abortCapture(
          "Microphone disconnected. The prior passage was kept.",
        );
        this.pause();
        this.disarm();
        this.sync();
      };
  }
  async setMode(mode) {
    const epoch = this.runningEpoch ?? this.epoch,
      arming = this.armingEpoch;
    await this.ready();
    if (epoch !== this.epoch || arming !== this.armingEpoch) return;
    if (this.passage) await this.finishCapture();
    if (mode === "record") {
      this.requireWriter();
      await this.microphone();
    } else this.releaseMic();
    if (epoch !== this.epoch || arming !== this.armingEpoch) return;
    this.mode = mode;
    if (this.playing) {
      this.schedule();
      if (mode === "record") this.beginCapture();
      this.rememberAudition();
    }
    this.sync();
  }
  async play() {
    const epoch = this.runningEpoch ?? this.epoch,
      arming = this.armingEpoch;
    await this.ready();
    if (epoch !== this.epoch || arming !== this.armingEpoch) return;
    if (active && active !== this) {
      await active.requestPause();
      active.disarm();
      active.backing = null;
      active.backingKey = null;
      active.sync();
    }
    document.querySelectorAll("audio, yt-audio").forEach((a) => a.pause());
    if (this.playing) return;
    if (this.passage) await this.finishCapture();
    if (this.sourceChanged && (this.mode !== "playback" || !this.solo))
      throw Error(
        "The source changed. Select Play back and enable Solo to listen to and save your preserved recording. Reload and Clear to start with the new source.",
      );
    if (
      (this.pendingBacking || this.backingKey !== this.selected ||
        this.backingInvalidated) &&
      (this.mode !== "playback" || !this.solo)
    ) {
      const loaded = await this.selectBacking(
        this.pendingBacking?.key ?? this.selected,
        this.pendingBacking ?? undefined,
      );
      if (!loaded) return;
    }
    if (this.position >= this.duration) this.position = 0;
    if (this.mode === "record") {
      this.requireWriter();
      await this.microphone();
    }
    if (epoch !== this.epoch || arming !== this.armingEpoch) return;
    active = this;
    this.playing = true;
    // Record starts after a two-bar lead-in; clicks fill any part before 0:00.
    this.recordFrom = this.mode === "record" ? this.position : null;
    this.from =
      this.recordFrom !== null && this.grid
        ? this.grid.leadStart(this.position)
        : this.position;
    this.anchor = this.ctx.currentTime + 0.05 - this.from;
    this.schedule();
    if (this.mode === "record") this.beginCapture();
    this.rememberAudition();
    this.sync();
    this.player()?.dispatchEvent(new Event("play"));
  }
  stopSources() {
    for (const s of this.sources) {
      try {
        s.stop();
        s.disconnect();
      } catch {}
    }
    this.sources = [];
    for (const { gain } of this.gains ?? []) gain.disconnect();
    this.gains = [];
  }
  player() {
    return this.section.querySelector(
      `practice-audio[data-backing="${this.selected}"]`,
    );
  }
  scheduleSource(buffer, start, end, offset, gain, local = false) {
    const now = Math.max(
      this.ctx.currentTime + 0.005,
      this.anchor + this.current(),
    );
    const lo = Math.max(this.current(), start, now - this.anchor),
      hi = Math.min(this.duration, end);
    if (hi <= lo) return;
    const source = this.ctx.createBufferSource();
    source.buffer = buffer;
    const level = this.ctx.createGain();
    level.gain.value = gain;
    source.connect(level);
    level.connect(local ? this.clip : this.backingBus);
    const entry = { gain: level, local };
    this.gains.push(entry);
    this.sources.push(source);
    source.onended = () => {
      source.disconnect();
      level.disconnect();
      this.sources = this.sources.filter((s) => s !== source);
      this.gains = this.gains.filter((g) => g !== entry);
    };
    source.start(this.anchor + lo, offset + lo - start, hi - lo);
  }
  schedule() {
    this.stopSources();
    if (this.backing)
      this.scheduleSource(
        this.backing,
        0,
        this.backing.duration,
        0,
        this.backingLevel(),
      );
    for (const beat of this.grid?.clicks(this.current(), 0) ?? [])
      this.click(beat);
    this.nextSegment = 0;
    this.scheduleLocal();
  }
  click({ t, pos }) {
    const at = this.anchor + t;
    if (at < this.ctx.currentTime) return;
    const tone = this.ctx.createOscillator(),
      level = this.ctx.createGain();
    tone.frequency.value = pos === 1 ? 1760 : 1320;
    level.gain.setValueAtTime(0.5, at);
    level.gain.exponentialRampToValueAtTime(0.001, at + 0.05);
    tone.connect(level).connect(this.clip);
    tone.onended = () => level.disconnect();
    tone.start(at);
    tone.stop(at + 0.05);
    this.sources.push(tone);
  }
  scheduleLocal() {
    if (this.mode !== "playback") return;
    const position = this.current(),
      horizon = position + 2;
    while (this.nextSegment < this.track.segments.length) {
      const s = this.track.segments[this.nextSegment];
      if (s.start / this.track.rate > horizon) break;
      this.nextSegment++;
      if (s.end / this.track.rate <= position) continue;
      const buffer = this.ctx.createBuffer(
        s.data.channels.length,
        s.data.channels[0].length,
        this.ctx.sampleRate,
      );
      s.data.channels.forEach((c, i) => buffer.copyToChannel(c, i));
      this.scheduleSource(
        buffer,
        s.start / this.track.rate,
        s.end / this.track.rate,
        s.offset / this.track.rate,
        this.trackGain,
        true,
      );
    }
  }
  beginCapture() {
    const rate = this.track.rate,
      start = Math.round(Math.max(this.current(), this.recordFrom ?? 0) * rate);
    const offset = this.latency(),
      anchor = Math.round(this.anchor * rate);
    this.passage = new CapturePassage({
      id: crypto.randomUUID(),
      start,
      anchor,
      offset,
      gain: 1,
      length: this.track.length,
    });
    this.capture.port.postMessage({
      type: "start",
      id: this.passage.id,
      start: anchor + start + offset,
    });
  }
  finishCapture() {
    if (!this.passage) return Promise.resolve();
    if (this.finishing) return this.finishing;
    if (this.current() * this.track.rate <= this.passage.start) {
      this.abortCapture(""); // stopped during the lead-in
      return Promise.resolve();
    }
    this.passage.end = Math.round(this.current() * this.track.rate);
    this.finishing = new Promise((resolve) => (this.finishResolve = resolve));
    this.capture.port.postMessage({
      type: "stop",
      id: this.passage.id,
      end: this.passage.anchor + this.passage.end + this.passage.offset,
    });
    this.finishTimeout = setTimeout(
      () => this.abortCapture("Input interrupted. The prior passage was kept."),
      (this.passage.offset / this.track.rate) * 1000 + 1500,
    );
    return this.finishing;
  }
  completeCapture() {
    const parts = this.passage.finish(this.passage.end);
    if (parts) {
      this.track.replace(this.passage.start, this.passage.end, parts);
      this.status("Passage recorded in this browser.");
      this.edited();
    } else
      this.status("Incomplete microphone input. The prior passage was kept.");
    this.endCapture();
  }
  endCapture() {
    clearTimeout(this.finishTimeout);
    this.passage = null;
    this.finishResolve?.();
    this.finishResolve = null;
    this.finishing = null;
  }
  abortCapture(message) {
    this.capture?.port.postMessage({ type: "cancel" });
    this.endCapture();
    this.status(message);
  }
  requestPause() {
    this.cancelBacking();
    return this.pause();
  }
  async pause() {
    if (!this.playing) return;
    this.rememberAudition();
    const finishing = this.finishCapture();
    this.position = Math.max(this.current(), this.recordFrom ?? 0);
    this.recordFrom = null;
    this.playing = false;
    this.stopSources();
    this.sync();
    await finishing;
  }
  async seek(position) {
    const playing = this.playing;
    await this.pause();
    this.disarm();
    this.position = Math.max(0, Math.min(this.duration ?? 0, position));
    this.sync();
    if (playing) await this.play();
  }
  meter(name, analyser) {
    let level = 0;
    if (analyser) {
      analyser.getFloatTimeDomainData((this.levels ??= new Float32Array(2048)));
      for (const v of this.levels) level = Math.max(level, Math.abs(v));
    }
    if (name === "mic" && level >= 1 && !this.clipped) {
      this.clipped = true;
      this.sync();
    }
    const db = level > 0 ? 20 * Math.log10(level) : -99;
    this.ui
      .querySelector(`[data-meter="${name}"]`)
      .style.setProperty("--lv", Math.max(0, Math.min(1, (db + 48) / 48)));
  }
  tick() {
    this.meter("mic", this.analyser);
    this.meter("backing", this.playing && this.backingMeter);
    const t = this.current();
    if (this.grid) {
      const { bar, beat } = this.grid.barAt(t);
      this.ui.querySelector("[data-bar]").textContent =
        `${bar < 0 ? "−" : ""}${Math.abs(bar)}.${beat}`;
    }
    this.ui.querySelector("[data-time]").textContent =
      `${t < 0 ? "−" : ""}${clock(Math.abs(t))} / ${clock(this.duration ?? 0, false)}`;
    this.draw();
    this.showStatus();
    if (!this.playing) return;
    this.scheduleLocal();
    this.rememberAudition();
    if (t >= this.duration) {
      this.run(async () => {
        await this.pause();
        this.disarm();
        this.sync();
      });
    }
    this.player()?.dispatchEvent(new Event("timeupdate"));
  }
  sync() {
    const ui = this.ui,
      armed = this.mode === "record",
      play = ui.querySelector('[data-action="play"]');
    if (play.dataset.playing !== String(this.playing)) {
      play.innerHTML = this.playing ? ICON.pause : ICON.play;
      play.dataset.playing = this.playing;
      play.setAttribute("aria-label", this.playing ? "Pause" : "Play");
    }
    ui.classList.toggle("armed", armed);
    ui.classList.toggle("recording", armed && this.playing);
    for (const b of ui.querySelectorAll('[data-action="record"]'))
      b.setAttribute("aria-pressed", armed);
    ui.querySelector('[data-action="mute"]').setAttribute(
      "aria-pressed",
      this.mode === "mute",
    );
    ui.querySelector('[data-action="solo"]').setAttribute(
      "aria-pressed",
      this.solo,
    );
    ui.querySelector('[data-action="undo"]').disabled = !this.track?.undo;
    ui.querySelector('[data-action="clip"]').classList.toggle("on", !!this.clipped);
    for (const b of ui.querySelectorAll("[data-view]"))
      b.setAttribute("aria-pressed", !this.view && b.dataset.view === this.zoom);
    const select = ui.querySelector('[data-control="backing"]'),
      keys = Object.keys(this.backingFiles()).filter(
        (k) => this.backingFiles()[k],
      );
    if (select.dataset.keys !== String(keys)) {
      select.replaceChildren(...keys.map((k) => new Option(label(k), k)));
      select.dataset.keys = keys;
    }
    select.value = this.pendingBacking?.key ?? this.selected;
    ui.querySelector('[data-draw="backing"]').setAttribute(
      "aria-busy", !!this.pendingBacking,
    );
    for (const key of ["backingGain", "trackGain", "inputGain"]) {
      const db = toDb(this[key]),
        input = ui.querySelector(`[data-control="${key}"]`);
      if (document.activeElement !== input) input.value = db;
      ui.querySelector(`[data-db="${key}"]`).textContent = dbText(db);
    }
    const latency = ui.querySelector('[data-control="offset"]');
    if (document.activeElement !== latency) latency.value = latencyMs();
    const a = this.audition;
    ui.querySelector("[data-heard]").textContent = !a
      ? "Whole song · your track alone, since you haven't listened to it with a backing yet"
      : a.solo
        ? "Whole song · your track solo, as you last listened"
        : `Whole song · ${label(a.backing)} ${dbText(toDb(a.backingGain))} + your track ${dbText(toDb(a.trackGain))}, as you last listened`;
    this.section.querySelectorAll("practice-audio").forEach((p) => p.update());
    this.showStatus();
  }
}
addEventListener("keydown", (e) => {
  const r = document.querySelector(".tabpanel.active section[data-song]")
      ?.recording,
    key = e.key.toLowerCase(),
    undo = (e.ctrlKey || e.metaKey) && !e.shiftKey && key === "z";
  if (
    !r?.supported ||
    e.defaultPrevented ||
    e.altKey ||
    ((e.ctrlKey || e.metaKey) && !undo) ||
    e.target.closest?.("input:not([type=range]), select, textarea, [contenteditable], dialog, #fbmenu")
  )
    return;
  const action = undo
    ? "undo"
    : { " ": "play", r: "record", m: "mute", s: "solo", home: "home" }[key];
  if (!action) return;
  e.preventDefault();
  r.act(action);
});
window.LocalRecording = { Recording };
