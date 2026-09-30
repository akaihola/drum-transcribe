import assert from 'node:assert/strict';
import {LocalTrack, CapturePassage} from '../src/drum_transcribe/static/recording-core.js';
const rate = 48000, length = 180 * rate;
const track = new LocalTrack(rate, length);
const original = new Float32Array(length).fill(.25);
track.replace(0, length, [{start:0, end:length, offset:0, data:{id:'old', channels:[original]}}]);
// 3 minutes, packet delivery unrelated to sample times, with 60 ms device delay.
const offset = 2880, anchor = 123456;
const take = new CapturePassage({id:'long', start:0, anchor, offset, length});
for (let p = 0; p < length; p += 4096) {
  const samples = new Float32Array(Math.min(4096, length - p));
  for (const onset of [rate, length - rate]) if (onset >= p && onset < p + samples.length) samples[onset - p] = .9;
  take.add({frame:anchor + offset + p, samples, valid:true});
}
track.replace(0, length, take.finish(length));
assert.equal(track.read(rate,1)[0], Math.fround(.9));
assert.equal(track.read(length-rate,1)[0], Math.fround(.9));
const before = track.read(0,length);
const punch = new CapturePassage({id:'punch', start:40*rate, anchor, offset, length});
for (let p = 40*rate; p < 47*rate; p += 4096)
  punch.add({frame:anchor+offset+p, samples:new Float32Array(4096), valid:true});
track.replace(40*rate,46*rate,punch.finish(46*rate));
assert.deepEqual(track.read(0,40*rate),before.subarray(0,40*rate));
assert.deepEqual(track.read(46*rate,length-46*rate),before.subarray(46*rate));
assert.ok(track.read(40*rate,6*rate).every(x=>x===0));
track.undoLast(); assert.deepEqual(track.read(0,length),before);
const bad = new CapturePassage({id:'bad', start:0, anchor:0, offset:0, length});
bad.add({frame:0,samples:new Float32Array(128),valid:false});
assert.equal(bad.finish(128),null);
const gap = new CapturePassage({id:'gap', start:0, anchor:0, offset:0, length});
gap.add({frame:128,samples:new Float32Array(128),valid:true});
assert.equal(gap.finish(256),null);
console.log('180 s alignment: 0 samples error at both onsets; 40–46 s silence replacement preserves all outside samples; Undo exact; invalid and missing capture rejected.');
const {wavHeader,encodeBlock} = await import('../src/drum_transcribe/static/recording-wav.js');
const header = new DataView(wavHeader(48000,2,48000));
assert.equal(header.getUint32(40,true),192000);
const encoded = new DataView(encodeBlock([new Float32Array([.75,-.75])],[new Float32Array([.75,-.75])],1,1));
assert.equal(encoded.getInt16(0,true),32767); assert.equal(encoded.getInt16(2,true),-32768);
console.log('WAV header spans the full timeline; identical listening/export hard peak limit; PCM16 endpoints correct.');
