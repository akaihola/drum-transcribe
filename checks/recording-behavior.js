(async () => {
  const r = document.querySelector(
    'section[data-song="taustanauha"]',
  ).recording;
  const assert = (ok, message) => {
    if (!ok) throw Error(message);
  };
  const pause = () => new Promise((resolve) => setTimeout(resolve, 200));
  await r.pause();
  await r.clear();
  const initial = {
    id: crypto.randomUUID(),
    channels: [new Float32Array(48000).fill(0.2)],
  };
  r.track.replace(48000, 96000, [
    { start: 48000, end: 96000, offset: 0, data: initial },
  ]);
  r.edited();
  await r.selectBacking("drumless");
  await r.setMode("playback");
  r.backingGain = 0.4;
  r.trackGain = 0.7;
  r.solo = false;
  r.balance();
  await r.play();
  await pause();
  await r.pause();
  const heard = JSON.stringify(r.audition);
  assert(
    r.audition.backing === "drumless" && r.audition.backingGain === 0.4,
    "Audition not remembered",
  );
  r.backingGain = 0.1;
  r.trackGain = 0.1;
  r.balance();
  assert(
    JSON.stringify(r.audition) === heard,
    "Paused controls changed audition",
  );
  await r.setMode("mute");
  await r.selectBacking("fused");
  await r.play();
  await pause();
  await r.pause();
  assert(
    JSON.stringify(r.audition) === heard,
    "Muted listening changed remembered backing",
  );
  const data = {
    id: crypto.randomUUID(),
    channels: [new Float32Array(48000).fill(0.4)],
  };
  r.track.replace(48000, 96000, [
    { start: 48000, end: 96000, offset: 0, data },
  ]);
  r.edited();
  const wav = await r.createWav(),
    decoded = await r.ctx.decodeAudioData(await wav.arrayBuffer());
  assert(decoded.length === r.track.length, "Export cropped the song");
  for (const frame of [0, 48000, 70000, r.track.length - 1]) {
    const expected = Math.max(
      -1,
      Math.min(
        1,
        (r.backing.getChannelData(0)[frame] ?? 0) * 0.4 +
          r.track.read(frame, 1)[0] * 0.7,
      ),
    );
    assert(
      Math.abs(decoded.getChannelData(0)[frame] - expected) < 0.00005,
      "Export did not use latest edit and remembered mix",
    );
  }
  r.offset = 1000;
  await r.importAudio(
    new File([wav], "finished-mix.wav", { type: "audio/wav" }),
  );
  assert(JSON.stringify(r.audition) === heard, "Import reset audition");
  assert(
    r.track.read(48000, 1)[0] === decoded.getChannelData(0)[48000],
    "Import applied microphone correction",
  );
  const before = r.track.segments;
  const originalPut = IDBObjectStore.prototype.put;
  IDBObjectStore.prototype.put = function () {
    throw new DOMException("Synthetic quota failure", "QuotaExceededError");
  };
  r.persist();
  await r.writes;
  IDBObjectStore.prototype.put = originalPut;
  assert(r.track.segments === before, "Storage failure discarded memory");
  const store = await import("/static/recording-store.js");
  assert(
    (await store.loadTrack(r.key)) !== null,
    "Storage failure lost committed track",
  );
  const message = r.ui.querySelector("[data-status]").textContent;
  assert(message.includes("Not saved"), "Storage failure was hidden");
  const getUserMedia = navigator.mediaDevices.getUserMedia;
  navigator.mediaDevices.getUserMedia = async () => {
    throw new DOMException("Denied for test", "NotAllowedError");
  };
  await r.run(() => r.setMode("record"));
  navigator.mediaDevices.getUserMedia = getUserMedia;
  assert(
    r.track.segments === before && r.mode === "playback",
    "Permission denial changed valid work",
  );
  await r.clear();
  await r.writes;
  assert((await store.loadTrack(r.key)) === null, "Clear recreated data");
  return {
    rememberedBacking: "drumless",
    pausedChangesIgnored: true,
    mutedAuditionIgnored: true,
    latestEditExported: true,
    wholeSongFrames: decoded.length,
    finishedMixImportAligned: true,
    quotaFailurePreservesTrack: true,
    permissionDenialPreservesTrack: true,
    clearComplete: true,
  };
})();
