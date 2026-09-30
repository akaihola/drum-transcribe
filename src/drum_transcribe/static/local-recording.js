import {LocalTrack, CapturePassage} from './recording-core.js';
import {loadTrack, saveTrack, clearTrack, peaks} from './recording-store.js';
let context, contextReady, active;
const MEDIA = 'audio, yt-audio, practice-audio';
class PracticeAudio extends HTMLElement {
  connectedCallback() {
    if (this.firstChild) return;
    this.innerHTML = `<button type="button">Play</button><input type="range" aria-label="Song position" min="0" max="1" step="0.001" value="0"><output>0:00</output>`;
    this.querySelector('button').onclick = () => this.owner.run(async () => {
      if (this.owner.playing && this.owner.selected === this.dataset.backing) await this.owner.pause();
      else { await this.owner.selectBacking(this.dataset.backing); await this.owner.play(); }
    });
    this.querySelector('input').oninput = e => this.owner.run(() => this.owner.seek(+e.target.value));
  }
  get paused() { return !this.owner?.playing || this.owner.selected !== this.dataset.backing; }
  get readyState() { return this.owner?.track ? 4 : 0; }
  get currentTime() { return this.owner?.current() ?? 0; }
  set currentTime(value) { this.owner.run(() => this.owner.seek(value)); }
  set volume(value) { this.owner?.setMaster(+value); }
  get volume() { return this.owner?.bus?.gain.value ?? 1; }
  play() { return this.owner.run(async () => { await this.owner.selectBacking(this.dataset.backing); await this.owner.play(); }); }
  pause() { if (!this.paused) return this.owner.run(() => this.owner.pause()); }
  update() {
    this.querySelector('button').textContent = this.paused ? 'Play' : 'Pause';
    const input = this.querySelector('input'); input.max = this.owner.duration ?? 1; input.value = this.currentTime;
    const t = Math.floor(this.currentTime); this.querySelector('output').textContent = `${Math.floor(t/60)}:${String(t%60).padStart(2,'0')}`;
  }
}
customElements.define('practice-audio', PracticeAudio);
async function audioContext() {
  if (!context) {
    context = new AudioContext({latencyHint:'interactive',sampleRate:48000});
    contextReady = context.audioWorklet.addModule('/static/recording-worklet.js');
  }
  const resumed = context.resume(); await contextReady; await resumed; return context;
}
export class Recording {
  constructor(section, version, project) {
    section.recording = this; this.section = section; this.version = version; this.project = project;
    this.mode = 'mute'; this.position = 0; this.playing = false;
    this.sources = []; this.offset = 60; this.inputGain = 1;
    this.backingGain = 1; this.trackGain = 1; this.solo = false;
    this.key = `${project}/${version.name}`; this.epoch = 0; this.writes = Promise.resolve();
    this.selected = 'src'; this.bindPlayers(); this.mount();
  }
  backingFiles() {
    return {src:this.version.source, drums:this.version.drums, drumless:this.version.drumless,
      ...Object.fromEntries(this.version.variants.map(v => [v.name,v.files['sonification.ogg']]))};
  }
  bindPlayers() {
    for (const [key, url] of Object.entries(this.backingFiles())) {
      const node = this.section.querySelector(`[data-piece="${key}"]`);
      const old = node?.querySelector(MEDIA); if (!old || !url) continue;
      if (old.tagName === 'PRACTICE-AUDIO') { old.owner = this; continue; }
      old.pause();
      const player = document.createElement('practice-audio'); player.dataset.backing = key; player.owner = this;
      old.replaceWith(player);
    }
  }
  update(version) {
    if (this.version.sourceIdentity !== version.sourceIdentity && this.track) {
      this.sourceChanged = true; this.abortCapture('The backing source changed. Download your take, then Clear to start with the new source.');
      this.run(async () => { await this.pause(); this.mode = 'mute'; this.sync(); });
    }
    this.version = version; this.bindPlayers(); this.sync();
  }
  setMaster(value) { if (this.bus) this.bus.gain.value = value; }
  mount() {
    this.ui = document.createElement('div'); this.ui.className = 'local-recording';
    this.ui.innerHTML = `<h3>Your drum recording</h3>
      <p>Record here with wired headphones. Audio stays in this browser.</p>
      <div class="record-controls"><button data-action="play">Play</button>
      <label>Local track <select data-control="mode"><option value="mute">Mute</option>
      <option value="playback">Play back</option><option value="record">Record</option></select></label>
      <label><input data-control="solo" type="checkbox"> Solo local track</label></div>
      <div class="record-controls"><label>Backing level <input data-control="backingGain" type="range" min="0" max="1" step="0.01" value="1"></label>
      <label>Recording level <input data-control="trackGain" type="range" min="0" max="1" step="0.01" value="1"></label>
      <label>Microphone input level <input data-control="inputGain" type="range" min="0" max="4" step="0.05" value="1"></label>
      <label>Capture correction, earlier by ms <input data-control="offset" type="number" min="0" max="1000" value="60"></label></div>
      <label>Song position <input data-control="position" type="range" min="0" max="1" step="0.001" value="0"></label>
      <canvas data-wave height="100" role="img" aria-label="Saved recording waveform and playhead"></canvas>
      <div class="record-controls"><label>Microphone <meter data-meter min="0" max="1" high="0.95" value="0"></meter></label>
      <button data-action="undo" disabled>Undo last passage</button><button data-action="clear">Clear local track</button></div>
      <output data-status role="status">Choose Record to enable the microphone. Play begins the passage.</output>`;
    this.section.querySelector('.flow').after(this.ui);
    this.ui.querySelector('[data-action="play"]').onclick = () => this.run(() => this.playing ? this.pause() : this.play());
    this.ui.querySelector('[data-control="mode"]').onchange = e => this.run(() => this.setMode(e.target.value));
    this.ui.querySelector('[data-control="offset"]').onchange = e => this.offset = Math.max(0, Math.min(1000, +e.target.value || 0));
    this.ui.querySelector('[data-control="position"]').oninput = e => this.run(() => this.seek(+e.target.value));
    for (const key of ['backingGain','trackGain','solo','inputGain']) this.ui.querySelector(`[data-control="${key}"]`).oninput = e => {
      this[key] = key === 'solo' ? e.target.checked : +e.target.value;
      if (key !== 'inputGain') this.balance();
    };
    this.ui.querySelector('[data-action="undo"]').onclick = () => this.run(async () => {
      await this.ready(); this.requireWriter(); await this.pause(); this.track.undoLast(); this.edited(); this.sync();
    });
    this.ui.querySelector('[data-action="clear"]').onclick = () => { this.epoch++; this.clear().catch(e => this.status(e.message)); };
    this.ui.querySelector('[data-wave]').onclick = e => {
      const rect = e.currentTarget.getBoundingClientRect();
      this.run(async () => { await this.ready(); await this.seek((e.clientX-rect.left)/rect.width*this.duration); });
    };
    this.resize = new ResizeObserver(() => { this.waveDirty = true; this.drawWave(); }); this.resize.observe(this.ui);
    window.addEventListener('pagehide', () => { this.abortCapture(''); this.releaseMic(); this.stopSources(); this.playing = false; this.mode = 'mute'; clearTimeout(this.auditionTimer); this.persist(); this.unlock?.(); this.writable = false; });
    this.timer = setInterval(() => this.tick(), 100);
  }
  status(message) { this.ui.querySelector('[data-status]').textContent = message; }
  run(fn) {
    this.queue = (this.queue ?? Promise.resolve()).then(fn).catch(async e => {
      await this.pause(); this.releaseMic();
      this.status(e.message); this.mode = 'mute'; this.sync();
    });
    return this.queue;
  }
  async ready() {
    if (this.track && this.bus) { this.ctx = await audioContext(); return; }
    if (!this.loading) this.loading = this.initialize().finally(() => this.loading = null);
    return this.loading;
  }
  async initialize() {
    this.ctx = await audioContext();
    if (!this.track) {
      const r = await fetch(this.version.source); if (!r.ok) throw Error('Backing could not be loaded. Try again.');
      this.backingKey = 'src';
      this.backing = await this.ctx.decodeAudioData(await r.arrayBuffer());
      this.track = new LocalTrack(this.ctx.sampleRate, this.backing.length);
      this.duration = this.backing.duration;
      await this.restore();
      this.ui.querySelector('[data-control="position"]').max = this.duration;
      this.bus = this.ctx.createGain(); this.bus.gain.value = +(localStorage.volume ?? 1);
      // Listening and export use the same hard peak limit, before master volume.
      this.clip = this.ctx.createWaveShaper(); this.clip.curve = new Float32Array([-1,1]);
      this.clip.connect(this.bus); this.bus.connect(this.ctx.destination);
      this.ctx.addEventListener('statechange', () => {
        if (this.ctx.state !== 'running' && this.playing) {
          this.abortCapture('Audio interrupted. The unfinished passage was kept.'); this.pause(); this.mode = 'mute'; this.sync();
        }
      });
    }
  }
  async restore() {
    if (navigator.locks) await new Promise(resolve => {
      navigator.locks.request(`drum-recording:${this.key}`, {ifAvailable:true}, lock => {
        this.writable = !!lock; resolve();
        if (lock) return new Promise(release => this.unlock = release);
      }).catch(e => { this.status(e.message); resolve(); });
    });
    try {
      const saved = await loadTrack(this.key);
      if (saved) {
        if (saved.rate !== this.track.rate) throw Error('Saved audio uses a different sample rate. Open it with the original audio settings.');
        this.track.segments = saved.segments; this.audition = saved.audition;
        this.sourceChanged = saved.sourceIdentity !== this.version.sourceIdentity || saved.length !== this.track.length;
        if (this.audition) {
          this.backingGain = this.audition.backingGain; this.trackGain = this.audition.trackGain; this.solo = this.audition.solo;
          this.ui.querySelector('[data-control="backingGain"]').value = this.backingGain;
          this.ui.querySelector('[data-control="trackGain"]').value = this.trackGain;
          this.ui.querySelector('[data-control="solo"]').checked = this.solo;
        }
        this.status(this.sourceChanged ? 'The backing source changed. Download your take, then Clear to start over.' : 'Recording restored from this browser.');
      }
    } catch (e) { this.storageUnavailable = true; this.status(`Browser storage unavailable: ${e.message}. New takes stay in memory; download them before closing.`); }
    if (!this.writable) this.status('Another tab is editing this version, or this browser has no track locks. Listening is available. Close the other tab and reload to record.');
    this.waveDirty = true; this.drawWave();
  }
  requireWriter(allowChanged = false) {
    if (!this.writable) throw Error('This version is open for editing in another tab. Close that tab and reload.');
    if (this.sourceChanged && !allowChanged) throw Error('Backing source changed. Download your take and Clear before recording.');
  }
  persist() {
    if (!this.track || !this.writable || this.sourceChanged) return;
    const epoch = this.epoch, segments = this.track.segments, undo = this.track.undo;
    const state = {rate:this.track.rate,length:this.track.length,sourceIdentity:this.version.sourceIdentity,audition:this.audition};
    this.writes = this.writes.catch(() => {}).then(async () => {
      if (epoch !== this.epoch) return;
      await saveTrack(this.key,state,segments,undo);
      if (epoch === this.epoch) this.status('Saved in this browser.');
    }).catch(e => { if (epoch === this.epoch) this.status(`Not saved: ${e.message}. Your take is still in memory. Download it before closing.`); });
    return this.writes;
  }
  edited() { for (const s of this.track.segments) peaks(s.data); this.waveDirty = true; this.drawWave(); this.persist(); this.sync(); }
  async clear() {
    await this.ready(); this.requireWriter(true); this.epoch++; clearTimeout(this.auditionTimer);
    this.abortCapture(''); this.position = this.current(); this.playing = false; this.stopSources(); this.releaseMic();
    this.mode = 'mute'; this.track.clear(); this.audition = null; this.sourceChanged = false; this.waveImage = null;
    this.backingGain = this.trackGain = 1; this.solo = false;
    this.ui.querySelector('[data-control="backingGain"]').value = 1;
    this.ui.querySelector('[data-control="trackGain"]').value = 1;
    this.ui.querySelector('[data-control="solo"]').checked = false;
    this.waveDirty = true; this.drawWave(); this.sync();
    this.writes = this.writes.catch(()=>{}).then(() => clearTrack(this.key));
    try { await this.writes; this.status('Local recording and remembered mix cleared.'); }
    catch (e) { this.status(`Memory cleared, but browser storage could not be cleared: ${e.message}. Retry Clear before closing.`); }
  }
  releaseMic() {
    if (this.stream) for (const t of this.stream.getTracks()) { t.onended = t.onmute = null; t.stop(); }
    this.input?.disconnect(); this.capture?.disconnect(); this.analyser?.disconnect();
    this.stream = this.input = this.capture = this.analyser = null;
  }
  drawWave() {
    const canvas = this.ui?.querySelector('[data-wave]'); if (!canvas || !this.track) return;
    const width = Math.max(1, Math.round(canvas.clientWidth)), height = 100;
    if (this.waveDirty || canvas.width !== width) {
      canvas.width = width; this.waveImage = document.createElement('canvas'); this.waveImage.width = width; this.waveImage.height = height;
      const g = this.waveImage.getContext('2d'); g.strokeStyle = '#0E7386'; g.fillStyle = 'rgba(14,115,134,.08)';
      for (const s of this.track.segments) {
        g.fillRect(s.start/this.track.length*width,0,(s.end-s.start)/this.track.length*width,height);
        const p = peaks(s.data); g.beginPath();
        for (let b=Math.floor(s.offset/256);b<Math.ceil((s.offset+s.end-s.start)/256);b++) {
          const x = (s.start+b*256-s.offset)/this.track.length*width;
          if (x < s.start/this.track.length*width || x > s.end/this.track.length*width) continue;
          g.moveTo(x,50-p[b*2]*45); g.lineTo(x,50-p[b*2+1]*45);
        }
        g.stroke();
      }
      this.waveDirty = false;
    }
    const g = canvas.getContext('2d'); g.clearRect(0,0,width,height); if (this.waveImage) g.drawImage(this.waveImage,0,0);
    if (this.passage) { g.fillStyle = 'rgba(166,99,0,.25)'; g.fillRect(this.passage.start/this.track.length*width,0,(this.current()-this.passage.start/this.track.rate)/this.duration*width,height); }
    g.strokeStyle = '#232019'; const x = this.current()/this.duration*width; g.beginPath(); g.moveTo(x,0); g.lineTo(x,height); g.stroke();
  }
  async selectBacking(key) {
    await this.ready(); if (!this.backingFiles()[key]) return;
    if (this.selected === key && this.backingKey === key) return;
    const response = await fetch(this.backingFiles()[key]);
    if (!response.ok) throw Error('This backing could not be loaded. Try again.');
    const buffer = await this.ctx.decodeAudioData(await response.arrayBuffer());
    if (this.passage) await this.finishCapture();
    this.selected = key; this.backingKey = key; this.backing = buffer;
    if (this.playing) { this.schedule(); if (this.mode === 'record') this.beginCapture(); this.rememberAudition(); }
    this.sync();
  }
  balance() {
    for (const {gain,local} of this.gains ?? []) gain.gain.value = local ? this.trackGain : this.solo ? 0 : this.backingGain;
    this.rememberAudition();
  }
  rememberAudition() {
    if (!this.playing || this.mode !== 'playback' || this.trackGain <= 0 || !this.track?.segments.length) return;
    this.audition = {backing:this.selected,backingGain:this.solo ? 0 : this.backingGain,trackGain:this.trackGain,solo:this.solo};
    clearTimeout(this.auditionTimer); this.auditionTimer = setTimeout(() => this.persist(),250);
  }
  current() { return this.playing ? Math.min(this.duration, Math.max(this.position, this.ctx.currentTime - this.anchor)) : this.position; }
  async microphone() {
    const epoch = this.epoch;
    if (this.stream?.getAudioTracks()[0]?.readyState === 'live') return;
    if (!isSecureContext || !navigator.mediaDevices) throw Error('Recording needs HTTPS or localhost. Open this page at a trusted HTTPS address.');
    const stream = await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,
      echoCancellation:false, noiseSuppression:false, autoGainControl:false}});
    if (epoch !== this.epoch) { stream.getTracks().forEach(t=>t.stop()); throw Error('Recording was cancelled.'); }
    this.stream = stream;
    const input = this.input = this.ctx.createMediaStreamSource(stream);
    this.analyser = this.ctx.createAnalyser(); this.analyser.fftSize = 256; this.meterValues = new Float32Array(256);
    input.connect(this.analyser);
    this.capture = new AudioWorkletNode(this.ctx, 'drum-capture', {outputChannelCount:[1]});
    input.connect(this.capture); this.capture.connect(this.ctx.destination);
    this.capture.port.onmessage = ({data}) => {
      if (data.id !== this.passage?.id) return;
      if (data.type === 'samples') this.passage.add(data);
      if (data.type === 'done') this.completeCapture();
    };
    stream.getAudioTracks()[0].onended = stream.getAudioTracks()[0].onmute = () => {
      this.abortCapture('Microphone disconnected. The prior passage was kept.'); this.pause(); this.mode = 'mute'; this.sync();
    };
  }
  async setMode(mode) {
    const epoch = this.epoch; await this.ready(); if (epoch !== this.epoch) return;
    if (this.passage) await this.finishCapture();
    if (mode === 'record') { this.requireWriter(); await this.microphone(); } else this.releaseMic();
    if (epoch !== this.epoch) return; this.mode = mode;
    if (this.playing) { this.schedule(); if (mode === 'record') this.beginCapture(); this.rememberAudition(); }
    this.sync();
  }
  async play() {
    const epoch = this.epoch; await this.ready(); if (epoch !== this.epoch) return;
    if (active && active !== this) { await active.pause(); active.mode = 'mute'; active.sync(); }
    document.querySelectorAll('audio, yt-audio').forEach(a => a.pause());
    if (this.playing) return;
    if (this.passage) await this.finishCapture();
    if (this.position >= this.duration) this.position = 0;
    if (this.mode === 'record') { this.requireWriter(); await this.microphone(); }
    if (epoch !== this.epoch) return; active = this; this.playing = true; this.anchor = this.ctx.currentTime + .05 - this.position;
    this.schedule(); if (this.mode === 'record') this.beginCapture(); this.rememberAudition(); this.sync();
    this.player()?.dispatchEvent(new Event('play'));
  }
  stopSources() { for (const s of this.sources) { try { s.stop(); s.disconnect(); } catch {} } this.sources = []; for (const {gain} of this.gains ?? []) gain.disconnect(); this.gains = []; }
  player() { return this.section.querySelector(`practice-audio[data-backing="${this.selected}"]`); }
  schedule() {
    this.stopSources(); this.gains = [];
    const when = Math.max(this.ctx.currentTime + .005, this.anchor + this.current());
    const position = Math.max(this.current(), when - this.anchor);
    const source = (buffer, start, end, offset, gain, local = false) => {
      const lo = Math.max(position, start), hi = Math.min(this.duration, end);
      if (hi <= lo) return;
      const s = this.ctx.createBufferSource(); s.buffer = buffer;
      const g = this.ctx.createGain(); g.gain.value = gain; s.connect(g); g.connect(this.clip); this.gains.push({gain:g,local});
      s.start(when + lo - position, offset + lo - start, hi - lo); this.sources.push(s);
    };
    source(this.backing,0,this.backing.duration,0,this.solo ? 0 : this.backingGain);
    if (this.mode === 'playback') for (const s of this.track.segments) {
      const buffer = this.ctx.createBuffer(s.data.channels.length,s.data.channels[0].length,this.ctx.sampleRate);
      s.data.channels.forEach((c,i) => buffer.copyToChannel(c,i));
      source(buffer,s.start/this.track.rate,s.end/this.track.rate,s.offset/this.track.rate,this.trackGain,true);
    }
  }
  beginCapture() {
    const rate = this.track.rate, start = Math.round(this.current()*rate);
    const offset = Math.round(this.offset * rate / 1000), anchor = Math.round(this.anchor*rate);
    this.passage = new CapturePassage({id:crypto.randomUUID(),start,anchor,offset,gain:this.inputGain,length:this.track.length});
    this.capture.port.postMessage({type:'start',id:this.passage.id,start:anchor+start+offset});
    this.status('Recording. Only the passage crossed by the playhead will change.');
  }
  finishCapture() {
    if (!this.passage) return Promise.resolve();
    if (this.finishing) return this.finishing;
    this.passage.end = Math.round(this.current()*this.track.rate);
    this.finishing = new Promise(resolve => this.finishResolve = resolve);
    this.capture.port.postMessage({type:'stop', id:this.passage.id,
      end:this.passage.anchor+this.passage.end+this.passage.offset});
    this.finishTimeout = setTimeout(() => this.abortCapture('Input interrupted. The prior passage was kept.'), this.offset + 1500);
    return this.finishing;
  }
  completeCapture() {
    const parts = this.passage.finish(this.passage.end);
    if (parts) { this.track.replace(this.passage.start,this.passage.end,parts); this.status('Passage recorded in this browser.'); this.edited(); }
    else this.status('Incomplete microphone input. The prior passage was kept.');
    this.endCapture();
  }
  endCapture() {
    clearTimeout(this.finishTimeout); this.passage = null; this.finishResolve?.(); this.finishResolve = null; this.finishing = null;
  }
  abortCapture(message) { this.capture?.port.postMessage({type:'cancel'}); this.endCapture(); this.status(message); }
  async pause() {
    if (!this.playing) return;
    const finishing = this.finishCapture(); this.position = this.current(); this.playing = false; this.stopSources(); this.sync(); await finishing;
  }
  async seek(position) {
    const playing = this.playing; await this.pause(); this.mode = 'mute'; this.releaseMic();
    this.position = Math.max(0,Math.min(this.duration ?? 0,position)); this.sync(); if (playing) await this.play();
  }
  tick() {
    if (this.analyser) {
      this.analyser.getFloatTimeDomainData(this.meterValues);
      this.ui.querySelector('[data-meter]').value = Math.min(1,Math.max(...this.meterValues.map(Math.abs))*this.inputGain);
    } else this.ui.querySelector('[data-meter]').value = 0;
    this.drawWave(); if (!this.playing) return;
    if (this.current() >= this.duration) { this.run(async () => { await this.pause(); this.mode = 'mute'; this.releaseMic(); this.sync(); }); }
    this.ui.querySelector('[data-control="position"]').value = this.current();
    this.section.querySelectorAll('practice-audio').forEach(a => a.update());
    this.player()?.dispatchEvent(new Event('timeupdate'));
  }
  sync() { this.ui.querySelector('[data-action="play"]').textContent = this.playing ? 'Pause' : 'Play'; this.ui.querySelector('[data-control="mode"]').value = this.mode; this.ui.querySelector('[data-control="position"]').value = this.current(); this.section.querySelectorAll('practice-audio').forEach(a=>a.update()); this.ui.querySelector('[data-action="undo"]').disabled = !this.track?.undo; }
}
window.LocalRecording = {Recording};
