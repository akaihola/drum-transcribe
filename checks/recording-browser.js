(async () => {
  const {CapturePassage, LocalTrack} = await import('/static/recording-core.js');
  const rate = 48000, length = 180 * rate, offset = 2880;
  const ctx = new OfflineAudioContext(1, length + offset + 4096, rate);
  await ctx.audioWorklet.addModule('/static/recording-worklet.js');
  const capture = new AudioWorkletNode(ctx, 'drum-capture', {outputChannelCount:[1]});
  const take = new CapturePassage({id:'browser-test',start:0,anchor:0,offset,length});
  take.end = length;
  window.captureProbe = {take, ctx, messages:0};
  const done = new Promise(resolve => capture.port.onmessage = ({data}) => {
    window.captureProbe.messages++; window.captureProbe.last = {type:data.type, frame:data.frame, size:data.samples?.length};
    if (data.type === 'samples') take.add(data);
    else if (data.type === 'done') resolve();
  });
  const input = ctx.createBuffer(1,length+offset,rate);
  for (const frame of [rate+offset,length-rate+offset]) input.getChannelData(0)[frame] = .75;
  const source = ctx.createBufferSource(); source.buffer = input;
  source.connect(capture); capture.connect(ctx.destination);
  capture.port.postMessage({type:'start',id:take.id,start:offset,end:length+offset});
  capture.port.postMessage({type:'stop',id:take.id,end:length+offset}); source.start();
  const output = await ctx.startRendering();
  await Promise.race([done, new Promise((_,reject)=>setTimeout(()=>reject(Error(`Capture timeout at ${take.next}, messages ${window.captureProbe.messages}`)),3000))]);
  const parts = take.finish(length);
  if (!parts) throw Error('Invalid capture');
  const track = new LocalTrack(rate,length); track.replace(0,length,parts);
  if (track.read(rate,1)[0] !== .75 || track.read(length-rate,1)[0] !== .75) throw Error('Onset mismatch');
  if (!output.getChannelData(0).every(x=>x===0)) throw Error('Microphone echo');
  return {duration:180,sampleRate:rate,onsetErrorSamples:0,microphoneEcho:false,packets:parts.length};
})()
