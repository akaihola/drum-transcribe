import { LocalTrack, CapturePassage } from "./recording-core.js";
import { loadTrack, saveTrack, clearTrack, peaks } from "./recording-store.js";
let context, contextReady, active;
async function fingerprint(bytes) {
  return (
    "sha256:" +
    [...new Uint8Array(await crypto.subtle.digest("SHA-256", bytes))]
      .map((b) => b.toString(16).padStart(2, "0"))
      .join("")
  );
}
const MEDIA = "audio, yt-audio, practice-audio";
class PracticeAudio extends HTMLElement {
  connectedCallback() {
    if (this.firstChild) return;
    this.innerHTML = `<button type="button">Play</button><input type="range" aria-label="Song position" min="0" max="1" step="0.001" value="0"><output>0:00</output>`;
    this.querySelector("button").onclick = () =>
      this.owner.run(async () => {
        if (this.owner.playing && this.owner.selected === this.dataset.backing)
          await this.owner.pause();
        else {
          await this.owner.selectBacking(this.dataset.backing);
          await this.owner.play();
        }
      });
    this.querySelector("input").oninput = (e) =>
      this.owner.requestSeek(+e.target.value);
  }
  get paused() {
    return !this.owner?.playing || this.owner.selected !== this.dataset.backing;
  }
  get readyState() {
    return this.owner?.track ? 4 : 0;
  }
  get currentTime() {
    return this.owner?.current() ?? 0;
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
    return this.owner.run(async () => {
      await this.owner.selectBacking(this.dataset.backing);
      await this.owner.play();
    });
  }
  pause() {
    if (!this.paused) return this.owner.run(() => this.owner.pause());
  }
  update() {
    this.querySelector("button").textContent = this.paused ? "Play" : "Pause";
    const input = this.querySelector("input");
    input.max = this.owner.duration ?? 1;
    input.value = this.currentTime;
    const format = (t) =>
      `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, "0")}`;
    this.querySelector("output").textContent =
      `${format(this.currentTime)} / ${format(this.owner.duration ?? 0)}`;
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
    this.mode = "mute";
    this.position = 0;
    this.playing = false;
    this.sources = [];
    this.offset = 60;
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
    if (this.version.progress.sig !== version.progress.sig)
      this.backingInvalidated = true;
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
          this.mode = "mute";
          this.releaseMic();
          this.sync();
          this.status(
            "The backing source changed. Your prior recording is preserved. Reload to use the new song length.",
          );
        }
      });
    }
    this.version = version;
    this.bindPlayers();
    this.sync();
  }
  loadMetadata() {
    if (!this.supported || this.metadataRequested || this.track) return;
    this.metadataRequested = true;
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
        this.ui.querySelector('[data-control="position"]').max = this.duration;
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
    this.ui = document.createElement("div");
    this.ui.className = "local-recording";
    this.ui.innerHTML = `<h3>Your drum recording</h3>
      <p>Record here with wired headphones. Audio stays in this browser.</p>
      <div class="record-controls"><button data-action="play">Play</button>
      <label>Local track <select data-control="mode"><option value="mute">Mute</option>
      <option value="playback">Play back</option><option value="record">Record</option></select></label>
      <output data-backing></output><label><input data-control="solo" type="checkbox"> Solo local track</label></div>
      <div class="record-controls"><label>Backing level <input data-control="backingGain" type="range" min="0" max="1" step="0.01" value="1"></label>
      <label>Recording level <input data-control="trackGain" type="range" min="0" max="1" step="0.01" value="1"></label>
      <label>Microphone input level <input data-control="inputGain" type="range" min="0" max="4" step="0.05" value="1"></label>
      <label>Capture correction, earlier by ms <input data-control="offset" type="number" min="0" max="1000" value="60"></label></div>
      <label>Song position <input data-control="position" type="range" min="0" max="1" step="0.001" value="0"></label>
      <canvas data-wave height="100" role="img" aria-label="Saved recording waveform and playhead"></canvas>
      <div class="record-controls"><label>Microphone <meter data-meter min="0" max="1" high="0.95" value="0"></meter></label>
      <button data-action="undo" disabled>Undo last passage</button><button data-action="clear">Clear local track</button></div>
      <div class="record-controls"><button data-action="download">Download WAV</button>
      <label>Import audio <input data-import type="file" accept="audio/*,.wav,.flac,.ogg,.mp3,.m4a"></label></div>
      <details><summary>Recording help and timing</summary><p>Use localhost or HTTPS, a device microphone and wired headphones. The 60 ms capture correction is an unmeasured starting value. Adjust it with a known click or loopback recording. Positive values place new microphone audio earlier; they never move older passages. There is no count-in or live microphone echo. A temporary microphone buffer holds up to 171 ms while the microphone is open, so a slightly late button command can still capture the requested starting samples. Unrequested samples are discarded.</p>
      <p>Record while paused arms until Play. Pause keeps Record armed. Seeking disarms it. Recording replaces only the passage played, including silence. The source song sets the length.</p>
      <p>Download contains the whole song with the last mix or solo you actually listened to with the recording audible. Paused changes and muted listening are ignored. Before that, download is solo. Volume changes listening only. Import replaces the track after validation and keeps leading silence and gaps. An imported mix already contains its backing; use Solo to hear it by itself.</p>
      <p>Audio stays in this browser profile and website address, including its port. Browser cleanup or storage eviction can remove it. Download a copy before relying on it. Undo holds the last replaced passage during this visit. Clear frees this version's recording, waveform, Undo and remembered mix. Foreground desktop browsers are the initial target. Mobile and physical device latency have not been measured.</p><output data-estimates></output></details>
      <output data-storage></output><br><output data-status role="status">Choose Record to enable the microphone. Play begins the passage.</output>`;
    this.section.querySelector(".flow").after(this.ui);
    this.ui.querySelector('[data-action="play"]').onclick = () =>
      this.run(() => (this.playing ? this.pause() : this.play()));
    this.ui.querySelector('[data-control="mode"]').onchange = (e) =>
      this.run(() => this.setMode(e.target.value));
    this.ui.querySelector('[data-control="offset"]').onchange = (e) =>
      (this.offset = Math.max(0, Math.min(1000, +e.target.value || 0)));
    this.ui.querySelector('[data-control="position"]').oninput = (e) =>
      this.requestSeek(+e.target.value);
    for (const key of ["backingGain", "trackGain", "solo", "inputGain"])
      this.ui.querySelector(`[data-control="${key}"]`).oninput = (e) => {
        this[key] = key === "solo" ? e.target.checked : +e.target.value;
        if (key !== "inputGain") this.balance();
        else if (this.inputLevel) this.inputLevel.gain.value = this.inputGain;
      };
    this.ui.querySelector('[data-action="download"]').onclick = () =>
      this.run(() => this.download());
    this.ui.querySelector("[data-import]").onchange = (e) => {
      const file = e.target.files[0];
      if (file) this.run(() => this.importAudio(file));
      e.target.value = "";
    };
    this.ui.querySelector('[data-action="undo"]').onclick = () =>
      this.run(async () => {
        await this.ready();
        this.requireWriter();
        await this.pause();
        this.track.undoLast();
        this.edited();
        this.sync();
      });
    this.ui.querySelector('[data-action="clear"]').onclick = () => {
      this.epoch++;
      this.clear().catch((e) => this.status(e.message));
    };
    this.ui.querySelector("[data-wave]").onclick = (e) => {
      const rect = e.currentTarget.getBoundingClientRect();
      this.run(async () => {
        await this.ready();
        await this.seek(((e.clientX - rect.left) / rect.width) * this.duration);
      });
    };
    this.resize = new ResizeObserver(() => {
      this.waveDirty = true;
      this.drawWave();
    });
    this.resize.observe(this.ui);
    window.addEventListener("pagehide", () => {
      this.abortCapture("");
      this.releaseMic();
      this.stopSources();
      this.playing = false;
      this.mode = "mute";
      clearTimeout(this.auditionTimer);
      this.persist();
      this.writes.finally(() => this.unlock?.()).catch(() => {});
      this.writable = false;
    });
    if (!this.supported) {
      this.ui
        .querySelectorAll("button,input,select")
        .forEach((control) => (control.disabled = true));
      this.status(
        "Local recording needs HTTPS or localhost and a browser with AudioWorklet. The original players still work.",
      );
    }
    window.addEventListener("pageshow", (e) => {
      if (e.persisted)
        this.status(
          "Reload this page to reopen the local recording for editing.",
        );
    });
    this.timer = setInterval(() => this.tick(), 100);
  }
  storageMessage(message) {
    this.ui.querySelector("[data-storage]").textContent = message;
  }
  status(message) {
    this.ui.querySelector("[data-status]").textContent = message;
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
        this.releaseMic();
        this.status(e.message);
        this.mode = "mute";
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
      this.ui.querySelector('[data-control="position"]').max = this.duration;
      this.bus = this.ctx.createGain();
      this.bus.gain.value = +(localStorage.volume ?? 1);
      // Listening and export use the same hard peak limit, before master volume.
      this.clip = this.ctx.createWaveShaper();
      this.clip.curve = new Float32Array([-1, 1]);
      this.clip.connect(this.bus);
      this.bus.connect(this.ctx.destination);
      this.ctx.addEventListener("statechange", () => {
        if (this.ctx.state !== "running" && this.playing) {
          this.abortCapture(
            "Audio interrupted. The unfinished passage was kept.",
          );
          this.pause();
          this.mode = "mute";
          this.releaseMic();
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
      if (saved) {
        this.cleared = false;
        if (saved.rate !== this.track.rate)
          throw Error(
            "Saved audio uses a different sample rate. Open it with the original audio settings.",
          );
        this.track.segments = saved.segments;
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
          this.ui.querySelector('[data-control="backingGain"]').value =
            this.backingGain;
          this.ui.querySelector('[data-control="trackGain"]').value =
            this.trackGain;
          this.ui.querySelector('[data-control="solo"]').checked = this.solo;
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
    this.waveDirty = true;
    this.drawWave();
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
          this.storageMessage("Saved in this browser.");
          this.status("Saved in this browser.");
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
  edited() {
    this.cleared = false;
    for (const s of this.track.segments) peaks(s.data);
    this.waveDirty = true;
    this.drawWave();
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
    const segments = [];
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
        data: { id: crypto.randomUUID(), channels },
      });
    }
    if (epoch !== this.epoch) return;
    await this.pause();
    if (epoch !== this.epoch) return;
    this.mode = "mute";
    this.releaseMic();
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
    clearTimeout(this.auditionTimer);
    this.cancelExport();
    this.abortCapture("");
    this.position = this.current();
    this.playing = false;
    this.stopSources();
    this.releaseMic();
    this.mode = "mute";
    this.cleared = true;
    if (this.track) {
      this.track.clear();
      this.track.length = this.sourceFrames;
      this.duration = this.sourceFrames / this.track.rate;
    }
    this.audition = null;
    this.sourceChanged = false;
    this.waveImage = null;
    this.backingGain = this.trackGain = 1;
    this.solo = false;
    this.ui.querySelector('[data-control="backingGain"]').value = 1;
    this.ui.querySelector('[data-control="trackGain"]').value = 1;
    this.ui.querySelector('[data-control="solo"]').checked = false;
    this.waveDirty = true;
    const canvas = this.ui.querySelector("[data-wave]");
    canvas.getContext("2d").clearRect(0, 0, canvas.width, canvas.height);
    this.drawWave();
    this.sync();
    this.writes = this.writes.catch(() => {}).then(() => clearTrack(this.key));
    try {
      await this.writes;
      this.restoreFailed = false;
      this.storageMessage("No saved local recording.");
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
  drawWave() {
    const canvas = this.ui?.querySelector("[data-wave]");
    if (!canvas || !this.track) return;
    const width = Math.max(1, Math.round(canvas.clientWidth)),
      height = 100;
    if (this.waveDirty || canvas.width !== width) {
      canvas.width = width;
      this.waveImage = document.createElement("canvas");
      this.waveImage.width = width;
      this.waveImage.height = height;
      const g = this.waveImage.getContext("2d");
      g.strokeStyle = "#0E7386";
      g.fillStyle = "rgba(14,115,134,.08)";
      for (const s of this.track.segments) {
        g.fillRect(
          (s.start / this.track.length) * width,
          0,
          ((s.end - s.start) / this.track.length) * width,
          height,
        );
        const p = peaks(s.data);
        g.beginPath();
        for (
          let b = Math.floor(s.offset / 256);
          b < Math.ceil((s.offset + s.end - s.start) / 256);
          b++
        ) {
          const x =
            ((s.start + b * 256 - s.offset) / this.track.length) * width;
          if (
            x < (s.start / this.track.length) * width ||
            x > (s.end / this.track.length) * width
          )
            continue;
          g.moveTo(x, 50 - p[b * 2] * 45);
          g.lineTo(x, 50 - p[b * 2 + 1] * 45);
        }
        g.stroke();
      }
      this.waveDirty = false;
    }
    const g = canvas.getContext("2d");
    g.clearRect(0, 0, width, height);
    if (this.waveImage) g.drawImage(this.waveImage, 0, 0);
    if (this.passage) {
      g.fillStyle = "rgba(166,99,0,.25)";
      g.fillRect(
        (this.passage.start / this.track.length) * width,
        0,
        ((this.current() - this.passage.start / this.track.rate) /
          this.duration) *
          width,
        height,
      );
    }
    g.strokeStyle = "#232019";
    const x = (this.current() / this.duration) * width;
    g.beginPath();
    g.moveTo(x, 0);
    g.lineTo(x, height);
    g.stroke();
  }
  async selectBacking(key) {
    const epoch = this.runningEpoch ?? this.epoch;
    await this.ready();
    if (!this.backingFiles()[key]) return;
    if (
      this.selected === key &&
      this.backingKey === key &&
      !this.backingInvalidated
    )
      return;
    const response = await fetch(this.backingFiles()[key]);
    if (!response.ok)
      throw Error("This backing could not be loaded. Try again.");
    const buffer = await this.ctx.decodeAudioData(await response.arrayBuffer());
    if (epoch !== this.epoch) return;
    if (this.passage) await this.finishCapture();
    if (epoch !== this.epoch) return;
    this.selected = key;
    this.backingKey = key;
    this.backing = buffer;
    this.backingInvalidated = false;
    if (this.playing) {
      this.schedule();
      if (this.mode === "record") this.beginCapture();
      this.rememberAudition();
    }
    this.sync();
  }
  backingLevel() {
    return this.mode === "playback" && this.solo ? 0 : this.backingGain;
  }
  deactivate() {
    this.armingEpoch = (this.armingEpoch ?? 0) + 1;
    return this.run(async () => {
      await this.pause();
      this.mode = "mute";
      this.releaseMic();
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
          Math.max(this.position, this.ctx.currentTime - this.anchor),
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
    this.analyser.fftSize = 256;
    this.meterValues = new Float32Array(256);
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
        this.mode = "mute";
        this.releaseMic();
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
    if (mode === "record" && !this.playing)
      this.status("Record armed. Press Play to begin replacing this passage.");
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
      await active.pause();
      active.mode = "mute";
      active.releaseMic();
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
      (this.backingKey !== this.selected || this.backingInvalidated) &&
      (this.mode !== "playback" || !this.solo)
    )
      await this.selectBacking(this.selected);
    if (this.position >= this.duration) this.position = 0;
    if (this.mode === "record") {
      this.requireWriter();
      await this.microphone();
    }
    if (epoch !== this.epoch || arming !== this.armingEpoch) return;
    active = this;
    this.playing = true;
    this.anchor = this.ctx.currentTime + 0.05 - this.position;
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
    level.connect(this.clip);
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
    this.nextSegment = 0;
    this.scheduleLocal();
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
      start = Math.round(this.current() * rate);
    const offset = Math.round((this.offset * rate) / 1000),
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
    this.status(
      "Recording. Only the passage crossed by the playhead will change.",
    );
  }
  finishCapture() {
    if (!this.passage) return Promise.resolve();
    if (this.finishing) return this.finishing;
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
  async pause() {
    if (!this.playing) return;
    this.rememberAudition();
    const finishing = this.finishCapture();
    this.position = this.current();
    this.playing = false;
    this.stopSources();
    this.sync();
    await finishing;
  }
  async seek(position) {
    const playing = this.playing;
    await this.pause();
    this.mode = "mute";
    this.releaseMic();
    this.position = Math.max(0, Math.min(this.duration ?? 0, position));
    this.sync();
    if (playing) await this.play();
  }
  tick() {
    if (this.analyser) {
      this.analyser.getFloatTimeDomainData(this.meterValues);
      this.ui.querySelector("[data-meter]").value = Math.min(
        1,
        Math.max(...this.meterValues.map(Math.abs)),
      );
    } else this.ui.querySelector("[data-meter]").value = 0;
    this.drawWave();
    if (!this.playing) return;
    this.scheduleLocal();
    this.rememberAudition();
    if (this.current() >= this.duration) {
      this.run(async () => {
        await this.pause();
        this.mode = "mute";
        this.releaseMic();
        this.sync();
      });
    }
    this.ui.querySelector('[data-control="position"]').value = this.current();
    this.section.querySelectorAll("practice-audio").forEach((a) => a.update());
    this.player()?.dispatchEvent(new Event("timeupdate"));
  }
  sync() {
    this.ui.querySelector('[data-action="play"]').textContent = this.playing
      ? "Pause"
      : "Play";
    this.ui.querySelector('[data-control="mode"]').value = this.mode;
    this.ui.querySelector('[data-control="position"]').value = this.current();
    this.section.querySelectorAll("practice-audio").forEach((a) => a.update());
    this.ui.querySelector('[data-action="undo"]').disabled = !this.track?.undo;
    this.ui.querySelector('[data-action="download"]').title = this.audition
      ? this.audition.solo
        ? "Whole song, recording solo"
        : `Whole song, recording mixed with ${this.audition.backing}`
      : "Whole song, recording solo before any audition";
    this.ui.querySelector("[data-backing]").textContent =
      "Backing: " +
      ({ src: "original", drums: "drums stem", drumless: "without drums" }[
        this.selected
      ] ?? this.selected + " sonification");
  }
}
window.LocalRecording = { Recording };
