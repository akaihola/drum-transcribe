import {LocalTrack, CapturePassage} from './recording-core.js';
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
    context = new AudioContext({latencyHint:'interactive'});
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
  update(version) { this.version = version; this.bindPlayers(); this.sync(); }
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
    this.timer = setInterval(() => this.tick(), 100);
  }
  status(message) { this.ui.querySelector('[data-status]').textContent = message; }
  run(fn) {
    this.queue = (this.queue ?? Promise.resolve()).then(fn).catch(e => {
      this.status(e.message); this.mode = 'mute'; this.sync();
    });
    return this.queue;
  }
  async ready() {
    this.ctx = await audioContext();
    if (!this.track) {
      const r = await fetch(this.version.source); if (!r.ok) throw Error('Backing could not be loaded. Try again.');
      this.backingKey = 'src';
      this.backing = await this.ctx.decodeAudioData(await r.arrayBuffer());
      this.track = new LocalTrack(this.ctx.sampleRate, this.backing.length);
      this.duration = this.backing.duration;
      this.ui.querySelector('[data-control="position"]').max = this.duration;
      this.bus = this.ctx.createGain(); this.bus.gain.value = +(localStorage.volume ?? 1);
      // Listening and export use the same hard peak limit, before master volume.
      this.clip = this.ctx.createWaveShaper(); this.clip.curve = new Float32Array([-1,-1,0,1,1]);
      this.clip.connect(this.bus); this.bus.connect(this.ctx.destination);
      this.ctx.addEventListener('statechange', () => {
        if (this.ctx.state !== 'running' && this.playing) {
          this.abortCapture('Audio interrupted. The unfinished passage was kept.'); this.pause(); this.mode = 'mute'; this.sync();
        }
      });
    }
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
  }
  current() { return this.playing ? Math.min(this.duration, Math.max(this.position, this.ctx.currentTime - this.anchor)) : this.position; }
  async microphone() {
    if (this.stream?.getAudioTracks()[0]?.readyState === 'live') return;
    if (!isSecureContext || !navigator.mediaDevices) throw Error('Recording needs HTTPS or localhost. Open this page at a trusted HTTPS address.');
    const stream = await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,
      echoCancellation:false, noiseSuppression:false, autoGainControl:false}});
    this.stream = stream;
    const input = this.ctx.createMediaStreamSource(stream);
    this.capture = new AudioWorkletNode(this.ctx, 'drum-capture', {outputChannelCount:[1]});
    input.connect(this.capture); this.capture.connect(this.ctx.destination);
    this.capture.port.onmessage = ({data}) => {
      if (data.id !== this.passage?.id) return;
      if (data.type === 'samples') this.passage.add(data);
      if (data.type === 'done') this.completeCapture();
    };
    stream.getAudioTracks()[0].onended = () => {
      this.abortCapture('Microphone disconnected. The prior passage was kept.'); this.pause(); this.mode = 'mute'; this.sync();
    };
  }
  async setMode(mode) {
    await this.ready();
    if (this.passage) await this.finishCapture();
    if (mode === 'record') await this.microphone();
    this.mode = mode;
    if (this.playing) { this.schedule(); if (mode === 'record') this.beginCapture(); this.rememberAudition(); }
    this.sync();
  }
  async play() {
    await this.ready();
    if (active && active !== this) { await active.pause(); active.mode = 'mute'; active.sync(); }
    document.querySelectorAll('audio, yt-audio').forEach(a => a.pause());
    if (this.playing) return;
    if (this.passage) await this.finishCapture();
    if (this.position >= this.duration) this.position = 0;
    if (this.mode === 'record') await this.microphone();
    active = this; this.playing = true; this.anchor = this.ctx.currentTime + .05 - this.position;
    this.schedule(); if (this.mode === 'record') this.beginCapture(); this.rememberAudition(); this.sync();
    this.player()?.dispatchEvent(new Event('play'));
  }
  stopSources() { for (const s of this.sources) { try { s.stop(); } catch {} } this.sources = []; }
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
    if (parts) { this.track.replace(this.passage.start,this.passage.end,parts); this.status('Passage recorded in this browser.'); }
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
    const playing = this.playing; await this.pause(); this.mode = 'mute';
    this.position = Math.max(0,Math.min(this.duration ?? 0,position)); this.sync(); if (playing) await this.play();
  }
  tick() {
    if (!this.playing) return;
    if (this.current() >= this.duration) { this.run(async () => { await this.pause(); this.mode = 'mute'; this.sync(); }); }
    this.ui.querySelector('[data-control="position"]').value = this.current();
    this.section.querySelectorAll('practice-audio').forEach(a => a.update());
    this.player()?.dispatchEvent(new Event('timeupdate'));
  }
  sync() { this.ui.querySelector('[data-action="play"]').textContent = this.playing ? 'Pause' : 'Play'; this.ui.querySelector('[data-control="mode"]').value = this.mode; this.ui.querySelector('[data-control="position"]').value = this.current(); this.section.querySelectorAll('practice-audio').forEach(a=>a.update()); }
}
window.LocalRecording = {Recording};
