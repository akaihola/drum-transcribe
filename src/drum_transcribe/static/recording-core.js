// Sparse song-time intervals. Edits retain chunk references, never copy the song.
export class LocalTrack {
  constructor(rate, length) {
    this.rate = rate;
    this.length = length;
    this.segments = [];
    this.undo = null;
  }
  replace(start, end, segments) {
    start = Math.max(0, start);
    end = Math.min(this.length, end);
    if (end <= start) return;
    this.undo = this.segments;
    const keep = [];
    for (const s of this.segments) {
      if (s.end <= start || s.start >= end) keep.push(s);
      else {
        if (s.start < start) keep.push({ ...s, end: start });
        if (s.end > end)
          keep.push({ ...s, start: end, offset: s.offset + end - s.start });
      }
    }
    this.segments = [...keep, ...segments].sort((a, b) => a.start - b.start);
  }
  // Moves microphone takes to a new latency correction (frames). Each chunk
  // keeps the correction it sits at, so moving back and forth loses nothing;
  // chunks may reach past the song ends. Imported audio has none and stays.
  realign(offset) {
    const undo = this.undo,
      runs = [];
    this.segments = this.segments.filter((s) => {
      if (s.captureOffset === undefined || s.captureOffset === offset) return true;
      const shift = s.captureOffset - offset,
        moved = { ...s, start: s.start + shift, end: s.end + shift, captureOffset: offset },
        run = runs.at(-1);
      if (run?.at(-1).end === moved.start) run.push(moved);
      else runs.push([moved]);
      return false;
    });
    for (const run of runs) this.replace(run[0].start, run.at(-1).end, run);
    this.undo = undo;
    return runs.length > 0;
  }
  undoLast() {
    if (this.undo) {
      this.segments = this.undo;
      this.undo = null;
    }
  }
  clear() {
    this.segments = [];
    this.undo = null;
  }
  read(start, size, channel = 0) {
    const out = new Float32Array(size);
    for (const s of this.segments) {
      const lo = Math.max(start, s.start),
        hi = Math.min(start + size, s.end);
      if (hi > lo)
        out.set(
          s.data.channels[
            Math.min(channel, s.data.channels.length - 1)
          ].subarray(s.offset + lo - s.start, s.offset + hi - s.start),
          lo - start,
        );
    }
    return out;
  }
}

// Each take freezes its correction and audio-clock anchor. Packet arrival time is irrelevant.
export class CapturePassage {
  constructor({ id, start, anchor, offset, gain = 1, length }) {
    Object.assign(this, { id, start, anchor, offset, gain, length });
    this.end = null;
    this.parts = [];
    this.valid = true;
    this.next = start;
  }
  add({ frame, samples, valid }) {
    const position = frame - this.anchor - this.offset;
    const lo = Math.max(this.start, position),
      hi = Math.min(this.end ?? this.length, position + samples.length);
    if (hi <= lo) return;
    if (!valid || lo !== this.next) this.valid = false;
    const values = samples.subarray(lo - position, hi - position);
    if (this.gain !== 1)
      for (let i = 0; i < values.length; i++) values[i] *= this.gain;
    const data = { id: `${this.id}-${frame}`, channels: [values] };
    this.parts.push({
      start: lo,
      end: hi,
      offset: 0,
      take: this.id,
      data,
      captureOffset: this.offset,
    });
    this.next = hi;
  }
  finish(end) {
    this.end = end;
    const parts = this.parts
      .filter((s) => s.start < end)
      .map((s) => ({ ...s, end: Math.min(end, s.end) }));
    return this.valid && this.next >= end && end > this.start ? parts : null;
  }
}
export function mixSample(backing, recording, backingGain, recordingGain) {
  return Math.max(
    -1,
    Math.min(1, backing * backingGain + recording * recordingGain),
  );
}
