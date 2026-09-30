import { readFileSync } from "node:fs";
import { BeatGrid } from "../src/drum_transcribe/static/recording-grid.js";

const assert = (ok, message) => {
  if (!ok) throw Error(message);
};
// 4/4 at 120 bpm with one pickup beat before bar 1.
const times = Array.from({ length: 33 }, (_, i) => 0.25 + i * 0.5),
  positions = times.map((_, i) => ((i + 3) % 4) + 1),
  grid = new BeatGrid({ times, positions });
assert(grid.barStart(1) === 0.75 && grid.barStart(2) === 2.75, "bar starts");
assert(grid.barAt(0.8).bar === 1 && grid.barAt(0.8).beat === 1, "bar 1");
assert(grid.barAt(0.3).bar === 0 && grid.barAt(0.3).beat === 4, "pickup");
const lead = grid.leadStart(0);
assert(lead === -3.25, "count-in starts on the downbeat within two bars");
const clicks = grid.clicks(lead, 0);
assert(
  clicks.length === 7 && clicks[0].pos === 1 && clicks.at(-1).pos === 3,
  "count-in continues the grid into the song's pickup",
);
assert(grid.leadStart(10.9) === 6.9, "two bars of pre-roll mid-song");
const near = grid.clicks(grid.leadStart(2.75), 0);
assert(near.length === 3 && near[0].pos === 1, "short count-in near the start");
assert(grid.clicks(grid.leadStart(10.9), 0).length === 0, "no clicks mid-song");
assert(grid.barStart(40) === 78.75, "bars continue past the grid");
const file = process.argv[2]; // optional beats.json with a downbeat near 0:00
if (file) {
  const real = new BeatGrid(JSON.parse(readFileSync(file)));
  const clicks = real.clicks(real.leadStart(0), 0);
  assert(clicks.length === 8 && clicks[0].pos === 1, "real count-in");
}
console.log("Beat grid: bar numbers, pickup, two-bar lead-in and count-in clicks verified.");
