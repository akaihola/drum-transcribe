(async () => {
  const r = document.querySelector('section[data-song="taustanauha"]').recording;
  const assert = (ok,message) => { if (!ok) throw Error(message); };
  const {wavHeader} = await import('/static/recording-wav.js');
  const store = await import('/static/recording-store.js');
  await r.pause();await r.clear();
  const shortFrames=48000, samples=new Int16Array(shortFrames);
  samples.fill(8192,9600,19200);samples.fill(8192,28800,38400);
  const shortFile=new File([wavHeader(48000,1,shortFrames),samples],'short.wav',{type:'audio/wav'});
  r.offset=1000;await r.importAudio(shortFile);await r.writes;
  assert(r.track.read(0,9600).every(x=>x===0),'Short import lost leading silence');
  assert(r.track.read(19200,9600).every(x=>x===0),'Short import lost middle gap');
  assert(r.track.read(48000,r.track.length-48000).every(x=>x===0),'Short import not padded');
  const before=r.track.segments;
  try { await r.importAudio(new File([wavHeader(48000,1,r.track.length+128),new Uint8Array((r.track.length+128)*2)],'long.wav')); throw Error('Accepted long import'); }
  catch(e) { assert(e.message.includes('longer'),'Wrong long-import error'); }
  assert(r.track.segments===before,'Failed import replaced old audio');
  const other=r.key+'-storage-check';
  await store.saveTrack(other,{rate:48000,length:r.track.length,sourceIdentity:r.sourceIdentity,audition:null},before,null);
  r.persist();r.persist();await r.clear();await r.writes;
  assert(await store.loadTrack(r.key)===null,'Pending writes recreated Clear');
  assert((await store.loadTrack(other)).segments.length>0,'Clear erased another version');await store.clearTrack(other);
  const {LocalTrack}=await import('/static/recording-core.js');
  const take = {id:crypto.randomUUID(),channels:[new Float32Array(48000).fill(.25)]};
  r.track.replace(0,48000,[{start:0,end:48000,offset:0,data:take}]);r.edited();await r.writes;
  const fetch=window.fetch,requests=[];
  window.fetch=(url,options)=>{requests.push({url:String(url),method:options?.method ?? 'GET'});return fetch(url,options);};
  const getUserMedia=navigator.mediaDevices.getUserMedia;
  const sources=[];
  navigator.mediaDevices.getUserMedia=async()=>{const d=r.ctx.createMediaStreamDestination(),s=r.ctx.createConstantSource();s.offset.value=0;s.connect(d);s.start();sources.push(s);return d.stream};
  r.offset=0;await r.setMode('record');await r.play();await new Promise(res=>setTimeout(res,100));
  await r.ctx.suspend();await new Promise(res=>setTimeout(res,100));
  assert(!r.playing && r.mode==='mute' && !r.stream,'Audio interruption did not stop capture and playback');
  assert(r.track.read(0,48000).every(x=>x===.25),'Interrupted capture erased previous audio');
  await r.ctx.resume();
  await r.setMode('record');
  const position=r.ui.querySelector('[data-control="position"]');position.value=40;position.dispatchEvent(new Event('input'));await r.queue;
  assert(r.mode==='mute' && r.position===40,'Player seek did not disarm');
  await r.setMode('record');seekToBar(r.section,3);await r.queue;
  assert(r.mode==='mute','Score seek did not disarm');await r.pause();
  await r.setMode('record');await r.play();r.stream.getAudioTracks()[0].dispatchEvent(new Event('ended'));await new Promise(res=>setTimeout(res,100));
  assert(!r.playing && r.mode==='mute' && r.track.read(0,48000).every(x=>x===.25),'Removed microphone erased audio');
  navigator.mediaDevices.getUserMedia=getUserMedia;sources.forEach(s=>s.stop());window.fetch=fetch;
  assert(requests.every(q=>q.method==='GET'),'Recording sent a write request');
  const valid=r.track.segments;await r.writes;
  const saved=await store.loadTrack(r.key);saved.sourceIdentity='changed-test-source';
  await store.saveTrack(r.key,saved,valid,null);
  r.unlock();r.unlock=null;
  // Simulate re-opening this version without changing its actual source fixture.
  const section=document.createElement('section');section.dataset.song='source-check';
  const panel=document.createElement('div');panel.className='tabpanel';section.innerHTML='<div class="flow"></div>';panel.append(section);document.body.append(panel);
  const fresh=new LocalRecording.Recording(section,r.version,r.project);await fresh.ready();
  assert(fresh.sourceChanged && fresh.track.segments.length>0,'Changed source was not detected');
  let refused=false;try{fresh.requireWriter();}catch{refused=true;}assert(refused,'Changed source allowed overwrite');
  await fresh.clear();fresh.unlock();fresh.writable=false;clearInterval(fresh.timer);fresh.resize.disconnect();panel.remove();
  r.writable=false;r.track=new LocalTrack(48000,r.sourceFrames);
  return {shortImportPadded:true,gapsKept:true,longImportRejected:true,clearPreservesOtherVersion:true,
    audioInterruptionSafe:true,playerAndScoreSeeksDisarm:true,removedMicrophoneSafe:true,noRecordingUploads:true,sourceChangePreservesTrack:true};
})()
