import {wavHeader, encodeBlock} from './recording-wav.js';
let state, parts, next;
onmessage = ({data}) => {
  try {
    if (data.type === 'start') { state = data; next = 0; parts = [wavHeader(data.rate,data.channels,data.length)]; }
    else if (data.type === 'block') {
      parts.push(encodeBlock(data.backing,data.recording,state.backingGain,state.trackGain)); next += data.recording[0].length;
    }
    if (next < state.length) postMessage({type:'need',frame:next,size:Math.min(32768,state.length-next)});
    else { postMessage({type:'done',blob:new Blob(parts,{type:'audio/wav'})}); parts = null; }
  } catch (e) { postMessage({type:'error',message:e.message}); parts = null; }
};
