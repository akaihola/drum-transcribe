let database;
export function openStore() {
  if (!database) database = new Promise((resolve,reject) => {
    const request = indexedDB.open('drum-local-recordings',1);
    request.onupgradeneeded = () => {
      request.result.createObjectStore('tracks'); request.result.createObjectStore('chunks');
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
  return database;
}
function done(tx) { return new Promise((resolve,reject) => { tx.oncomplete = resolve; tx.onabort = () => reject(tx.error ?? Error('Local storage update aborted')); tx.onerror = () => {}; }); }
function range(key) { return IDBKeyRange.bound([key,''],[key,'\uffff']); }
export async function loadTrack(key) {
  const db = await openStore(), tx = db.transaction(['tracks','chunks'],'readonly');
  const completed = done(tx), meta = tx.objectStore('tracks').get(key), chunks = tx.objectStore('chunks').getAll(range(key));
  await completed;
  if (!meta.result) return null;
  const data = new Map(chunks.result.map(c => [c.id,c]));
  const segments = meta.result.segments.map(s => ({...s,data:data.get(s.id)}));
  if (segments.some(s => !s.data)) throw Error('A saved recording chunk is missing.');
  return {...meta.result,segments};
}
export async function saveTrack(key, state, segments, undo) {
  const db = await openStore(), tx = db.transaction(['tracks','chunks'],'readwrite'), completed = done(tx);
  try {
  const chunks = tx.objectStore('chunks'), refs = new Map([...segments,...(undo ?? [])].map(s=>[s.data.id,s.data]));
  // One transaction publishes the replacement map and all of its chunks.
  const cursor = chunks.openCursor(range(key)); cursor.onsuccess = () => {
    const c = cursor.result; if (!c) return;
    if (!refs.has(c.value.id)) c.delete(); c.continue();
  };
  for (const data of refs.values()) {
    // Existing immutable chunks need no new structured-clone copy.
    const k = [key,data.id], found = chunks.getKey(k);
    found.onsuccess = () => { try { if (found.result === undefined) chunks.put(data,k); } catch { tx.abort(); } };
  }
  tx.objectStore('tracks').put({...state,segments:segments.map(({data,...s})=>({...s,id:data.id}))},key);
  } catch (error) { tx.abort(); await completed.catch(()=>{}); throw error; }
  await completed;
}
export async function clearTrack(key) {
  const db = await openStore(), tx = db.transaction(['tracks','chunks'],'readwrite'), completed = done(tx);
  tx.objectStore('tracks').delete(key);
  const cursor = tx.objectStore('chunks').openCursor(range(key)); cursor.onsuccess = () => {
    const c = cursor.result; if (c) { c.delete(); c.continue(); }
  };
  await completed;
}
export function peaks(data) {
  if (data.peaks) return data.peaks;
  const size = Math.ceil(data.channels[0].length/256), result = new Float32Array(size*2);
  for (let bucket=0;bucket<size;bucket++) {
    let lo=0,hi=0;
    for (const channel of data.channels) for (let i=bucket*256;i<Math.min(channel.length,(bucket+1)*256);i++) { lo=Math.min(lo,channel[i]); hi=Math.max(hi,channel[i]); }
    result[bucket*2]=lo; result[bucket*2+1]=hi;
  }
  data.peaks = result; return result;
}
