// Bars and beats of beats.json, continued before the first beat at the opening
// tempo, so count-in clicks and bar numbers keep the song's pulse.
export class BeatGrid {
  constructor({ times, positions }, lead = 4) {
    const first = positions.indexOf(1),
      next = positions.indexOf(1, first + 1),
      perBar = next > first ? next - first : Math.max(...positions),
      span = Math.min(perBar * 2, times.length - 1),
      beat = span > 0 ? (times[span] - times[0]) / span : 0.5,
      pre = [];
    for (let k = perBar * lead; k > 0; k--)
      pre.push({
        t: times[0] - k * beat,
        pos: ((((positions[0] - 1 - k) % perBar) + perBar) % perBar) + 1,
      });
    this.beats = [...pre, ...times.map((t, i) => ({ t, pos: positions[i] }))];
    this.downbeats = this.beats.filter((b) => b.pos === 1).map((b) => b.t);
    // Bar 1 is the first downbeat of the song itself.
    this.first = this.downbeats.indexOf(times[first]);
  }
  barStart(bar) {
    const d = this.downbeats,
      i = bar - 1 + this.first,
      last = d.length - 1;
    if (i <= last) return d[Math.max(0, i)];
    return d[last] + (i - last) * (d[last] - d[last - 1]);
  }
  barAt(t) {
    const i = this.downbeats.findLastIndex((d) => d <= t),
      beat = this.beats.findLast((b) => b.t <= t);
    return { bar: i - this.first + 1, beat: beat?.pos ?? 1 };
  }
  // Two bars before the record point. Negative song time is count-in; it
  // starts on the nearest downbeat so the clicks count from "one".
  leadStart(t, bars = 2) {
    const { bar } = this.barAt(t),
      start = t - bars * (this.barStart(bar + 1) - this.barStart(bar));
    if (start >= 0) return start;
    return this.downbeats
      .filter((d) => d <= 0)
      .reduce((a, d) => (Math.abs(d - start) < Math.abs(a - start) ? d : a));
  }
  clicks(from, to) {
    return this.beats.filter((b) => b.t >= from && b.t < to);
  }
}
