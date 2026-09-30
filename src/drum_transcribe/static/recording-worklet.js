class DrumCapture extends AudioWorkletProcessor {
  constructor() {
    super();
    this.take = null;
    // Bounded pre-roll fills a start command that arrives just after its requested frame.
    // These 8192 samples never leave the processor unless a passage requests them.
    this.recent = new Float32Array(8192);
    this.valid = new Uint8Array(8192);
    this.nextFrame = 0;
    this.port.onmessage = ({ data }) => {
      if (data.type === "start") {
        this.take = {
          ...data,
          end: data.end ?? Infinity,
          used: 0,
          valid: true,
          samples: new Float32Array(4096),
        };
        for (
          let frame = Math.max(data.start, this.nextFrame - this.recent.length);
          frame < this.nextFrame;
          frame++
        )
          this.push(
            frame,
            this.recent[frame % this.recent.length],
            !!this.valid[frame % this.recent.length],
          );
      } else if (data.type === "stop" && this.take?.id === data.id)
        this.take.end = data.end;
      else if (data.type === "cancel") this.take = null;
    };
  }
  push(frame, sample, valid) {
    const t = this.take;
    if (!t || frame < t.start || frame >= t.end) return;
    if (!t.used) t.frame = frame;
    if (!valid) t.valid = false;
    t.samples[t.used++] = sample;
    if (t.used === t.samples.length) this.flush();
  }
  flush() {
    const t = this.take;
    if (!t.used) return;
    this.port.postMessage(
      {
        type: "samples",
        id: t.id,
        frame: t.frame,
        samples: t.samples.subarray(0, t.used),
        valid: t.valid,
      },
      [t.samples.buffer],
    );
    t.samples = new Float32Array(4096);
    t.used = 0;
    t.valid = true;
  }
  process(inputs, outputs) {
    // Output remains zero. The microphone is never echoed.
    const input = inputs[0]?.[0],
      size = outputs[0][0].length;
    for (let i = 0; i < size; i++) {
      const frame = currentFrame + i,
        sample = input?.[i] ?? 0,
        index = frame % this.recent.length;
      this.recent[index] = sample;
      this.valid[index] = input && Number.isFinite(sample) ? 1 : 0;
      this.push(frame, sample, !!this.valid[index]);
    }
    this.nextFrame = currentFrame + size;
    if (this.take && this.nextFrame >= this.take.end) {
      this.flush();
      this.port.postMessage({ type: "done", id: this.take.id });
      this.take = null;
    }
    return true;
  }
}
registerProcessor("drum-capture", DrumCapture);
