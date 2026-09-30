(async () => {
  const { encodeBlock } = await import("/static/recording-wav.js");
  const ctx = new OfflineAudioContext(1, 4096, 48000),
    backing = ctx.createBuffer(1, 4096, 48000),
    local = ctx.createBuffer(1, 4096, 48000);
  for (let i = 0; i < 4096; i++) {
    backing.getChannelData(0)[i] = Math.sin(i / 32) * 0.9;
    local.getChannelData(0)[i] = Math.cos(i / 16) * 0.9;
  }
  const curve = document.querySelector('section[data-song="taustanauha"]')
    .recording.clip.curve;
  const clip = ctx.createWaveShaper();
  clip.curve = curve;
  clip.connect(ctx.destination);
  for (const buffer of [backing, local]) {
    const source = ctx.createBufferSource();
    source.buffer = buffer;
    source.connect(clip);
    source.start();
  }
  const heard = (await ctx.startRendering()).getChannelData(0);
  const encoded = new DataView(
    encodeBlock([backing.getChannelData(0)], [local.getChannelData(0)], 1, 1),
  );
  let maxError = 0;
  for (let i = 0; i < 4096; i++) {
    const pcm = encoded.getInt16(i * 2, true) / 32768;
    maxError = Math.max(maxError, Math.abs(pcm - heard[i]));
  }
  if (maxError > 0.00005)
    throw Error(`Listening and export differ by ${maxError}`);
  return {
    listeningExportMaxSampleDifference: maxError,
    includesClipping: true,
  };
})();
