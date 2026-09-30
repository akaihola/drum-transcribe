class DrumCapture extends AudioWorkletProcessor {
  constructor() {
    super(); this.take = null;
    this.port.onmessage = ({data}) => {
      if (data.type === 'start') {
        this.take = {...data, end: data.end ?? Infinity, used: 0, valid: true, samples: new Float32Array(4096)};
      } else if (data.type === 'stop' && this.take?.id === data.id) this.take.end = data.end;
      else if (data.type === 'cancel') this.take = null;
    };
  }
  flush() {
    const t = this.take;
    if (!t.used) return;
    this.port.postMessage({type: 'samples', id: t.id, frame: t.frame,
      samples: t.samples.subarray(0, t.used), valid: t.valid}, [t.samples.buffer]);
    t.samples = new Float32Array(4096); t.used = 0; t.valid = true;
  }
  process(inputs, outputs) {
    // Output remains zero. The microphone is never echoed.
    const t = this.take, input = inputs[0]?.[0];
    const size = outputs[0][0].length;
    if (t) {
      for (let i = 0; i < size; i++) {
        const frame = currentFrame + i;
        if (frame < t.start || frame >= t.end) continue;
        if (!t.used) t.frame = frame;
        if (!input) t.valid = false;
        t.samples[t.used++] = input?.[i] ?? 0;
        if (t.used === t.samples.length) this.flush();
      }
      if (currentFrame + size >= t.end) {
        this.flush(); this.port.postMessage({type: 'done', id: t.id}); this.take = null;
      }
    }
    return true;
  }
}
registerProcessor('drum-capture', DrumCapture);
