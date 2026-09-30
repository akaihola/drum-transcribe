(async () => {
  const r = document.querySelector(
    'section[data-song="taustanauha"]',
  ).recording;
  await r.pause();
  const decode = async (url) =>
    r.ctx.decodeAudioData(await (await fetch(url)).arrayBuffer());
  const source =
    r.backingKey === "src" ? r.backing : await decode(r.version.source);
  const reference = source.getChannelData(0),
    rate = r.ctx.sampleRate;
  const lag = (samples, start) => {
    let best = -Infinity,
      frames = 0;
    for (let shift = -2400; shift <= 2400; shift += 16) {
      let dot = 0,
        a2 = 0,
        b2 = 0;
      for (let i = start; i < start + rate * 4; i += 16) {
        const a = reference[i],
          b = samples[i + shift] ?? 0;
        dot += a * b;
        a2 += a * a;
        b2 += b * b;
      }
      const corr = dot / Math.sqrt(a2 * b2);
      if (corr > best) {
        best = corr;
        frames = shift;
      }
    }
    return { offsetMs: (frames / rate) * 1000, correlation: best };
  };
  const drums = await decode(r.version.drums),
    drumless = await decode(r.version.drumless);
  const reconstructed = new Float32Array(
    Math.max(drums.length, drumless.length),
  );
  for (let i = 0; i < reconstructed.length; i++)
    reconstructed[i] =
      (drums.getChannelData(0)[i] ?? 0) + (drumless.getChannelData(0)[i] ?? 0);
  const result = {
    sourceDuration: source.duration,
    reconstructed: {
      start: lag(reconstructed, 8 * rate),
      end: lag(reconstructed, 180 * rate),
    },
    nodes: {},
  };
  for (const variant of r.version.variants) {
    const file = variant.files["sonification.ogg"];
    if (!file) continue;
    const buffer = await decode(file);
    result.nodes[variant.name] = {
      duration: buffer.duration,
      start: lag(buffer.getChannelData(0), 8 * rate),
      end: lag(buffer.getChannelData(0), 180 * rate),
    };
  }
  for (const node of [result.reconstructed, ...Object.values(result.nodes)])
    if (Math.abs(node.start.offsetMs) > 10 || Math.abs(node.end.offsetMs) > 10)
      throw Error(`Backing offset exceeds 10 ms: ${JSON.stringify(result)}`);
  return result;
})();
