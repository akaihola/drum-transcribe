import vm from 'node:vm';
import fs from 'node:fs';
import assert from 'node:assert/strict';
import {CapturePassage} from '../src/drum_transcribe/static/recording-core.js';
let Processor, packets=[];
const sandbox = {currentFrame:0,AudioWorkletProcessor:class {
  constructor() { this.port={postMessage(data,transfers=[]) {packets.push(structuredClone(data,{transfer:transfers}));}}; }
},registerProcessor(name,klass) {Processor=klass;}};
vm.runInNewContext(fs.readFileSync('src/drum_transcribe/static/recording-worklet.js','utf8'),sandbox);
const processor = new Processor();
function block(frame,size,input=true) {
  sandbox.currentFrame=frame;
  const samples=new Float32Array(size).fill(.75),output=new Float32Array(size);
  processor.process(input ? [[samples]] : [[]],[[output]]);
  assert.ok(output.every(x=>x===0),'No live microphone echo');
}
block(0,128);block(128,256);
processor.port.onmessage({data:{type:'start',id:'late-command',start:64}});
block(384,128); // Start requested in the bounded pre-roll.
processor.port.onmessage({data:{type:'stop',id:'late-command',end:448}});
block(512,256);
const take=new CapturePassage({id:'late-command',start:64,anchor:0,offset:0,length:1000}); take.end=448;
for (const packet of packets) if (packet.type==='samples') take.add(packet);
assert.equal(take.finish(448)?.reduce((n,s)=>n+s.end-s.start,0),384);
assert.ok(packets.some(p=>p.type==='done'));
packets=[];
processor.port.onmessage({data:{type:'start',id:'missing',start:768,end:1024}});block(768,256,false);
assert.ok(packets.find(p=>p.type==='samples').valid===false);
console.log('Late start and stop commands, bounded pre-roll, 128/256-frame blocks, capture tail, silent output and missing input verified.');
