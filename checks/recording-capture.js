(async () => {
  const r = document.querySelector(
    'section[data-song="taustanauha"]',
  ).recording;
  await r.pause();
  await r.clear();
  const original = new Float32Array(r.track.length).fill(0.25),
    data = { id: crypto.randomUUID(), channels: [original] };
  r.track.replace(0, r.track.length, [
    { start: 0, end: r.track.length, offset: 0, data },
  ]);
  r.edited();
  const getUserMedia = navigator.mediaDevices.getUserMedia;
  navigator.mediaDevices.getUserMedia = async () => {
    const destination = r.ctx.createMediaStreamDestination(),
      source = r.ctx.createConstantSource();
    source.offset.value = 0;
    source.connect(destination);
    source.start();
    window.silentMicrophone = source;
    return destination.stream;
  };
  if (!r.grid) throw Error("The fixture needs beats.json for the lead-in");
  const bar = r.grid.barAt(40).bar,
    twoBars = 2 * (r.grid.barStart(bar + 1) - r.grid.barStart(bar));
  await r.seek(40);
  r.offset = 60;
  await r.setMode("record");
  await r.play();
  const preRoll = 40 - r.from;
  while (r.current() < 46) await new Promise((res) => setTimeout(res, 20));
  const current = r.current;
  r.current = () => 46;
  await r.pause();
  r.current = current;
  const rate = r.track.rate;
  const result = {
    beforeUnchanged: r.track.read(0, 40 * rate).every((x) => x === 0.25),
    afterUnchanged: r.track
      .read(46 * rate, r.track.length - 46 * rate)
      .every((x) => x === 0.25),
    silenceReplaces: r.track.read(40 * rate, 6 * rate).every((x) => x === 0),
    pauseKeepsRecordArmed: r.mode === "record",
    preRollTwoBars: Math.abs(preRoll - twoBars) < 0.001,
  };
  r.track.undoLast();
  result.undoExact = r.track.read(0, r.track.length).every((x) => x === 0.25);
  r.edited();
  await r.seek(0);
  await r.setMode("record");
  const beats = () => r.grid.clicks(r.from, 0).length,
    undo = r.track.undo;
  await r.play();
  result.countInClicks =
    r.from < 0 &&
    beats() > 0 &&
    r.sources.filter((s) => s instanceof OscillatorNode).length === beats();
  await new Promise((res) => setTimeout(res, 300));
  await r.pause();
  result.pauseInCountInKeepsPoint =
    r.position === 0 && r.track.undo === undo && r.mode === "record";
  await r.setMode("mute");
  await r.play();
  r.offset = 0;
  await r.setMode("record");
  await new Promise((res) => setTimeout(res, 300));
  await r.setMode("mute");
  result.zeroOffsetLiveSwitchCaptures = r.track.undo !== null;
  await r.pause();
  navigator.mediaDevices.getUserMedia = getUserMedia;
  window.silentMicrophone.stop();
  await r.clear();
  await r.writes;
  if (Object.values(result).some((value) => value !== true))
    throw Error(JSON.stringify(result));
  return result;
})();
