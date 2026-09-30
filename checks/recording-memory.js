(async () => {
  const r = document.querySelector('section[data-song="taustanauha"]').recording;
  const {LocalTrack} = await import('/static/recording-core.js');
  await r.pause();
  const previous = {track:r.track,duration:r.duration,backing:r.backing,key:r.backingKey,audition:r.audition};
  const rate = 48000, frames = 600*rate;
  const track = new LocalTrack(rate,frames);
  for (let p=0;p<frames;p+=48000) {
    const samples = new Float32Array(48000); samples[100]=.75;
    track.segments.push({start:p,end:p+48000,offset:0,data:{id:`memory-${p}`,channels:[samples]}});
  }
  r.track=track; r.duration=600; r.backing=r.ctx.createBuffer(2,frames,rate); r.backingKey='src';
  r.audition={backing:'src',backingGain:.5,trackGain:1,solo:false};
  const before=performance.memory?.usedJSHeapSize ?? null, begin=performance.now();
  const wav = await r.createWav();
  const result = {duration:600,captureBytes:frames*4,backingBytes:frames*2*4,wavBytes:wav.size,
    exportMilliseconds:Math.round(performance.now()-begin),sampledJsHeapBefore:before,sampledJsHeapAfter:performance.memory?.usedJSHeapSize ?? null,
    exportBatchFrames:32768,extraFloatSamplesPerBatchAtMost:32768*2*2};
  r.track=previous.track;r.duration=previous.duration;r.backing=previous.backing;r.backingKey=previous.key;r.audition=previous.audition;r.waveDirty=true;
  return result;
})()
