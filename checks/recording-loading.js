// Run in an isolated fixture tab. Uses the real controls and Recording methods,
// with fake downloads/audio, and never changes browser-stored recordings.
(async () => {
  const r = document.querySelector(
    'section[data-song="taustanauha"]',
  ).recording;
  const assert = (ok, message) => {
    if (!ok) throw Error(message);
  };
  const until = async (condition) => {
    const deadline = performance.now() + 2000;
    while (!condition()) {
      if (performance.now() > deadline) throw Error("Loading check timed out");
      await new Promise((resolve) => setTimeout(resolve, 5));
    }
  };
  const deferreds = [], streams = [];
  const deferred = () => {
    let resolve, reject;
    const promise = new Promise((yes, no) => {
      resolve = yes;
      reject = no;
    });
    const value = { promise, resolve, reject };
    deferreds.push(value);
    return value;
  };
  assert(!r.passage && !r.stream, "Use a fixture tab without microphone capture");
  await r.queue;
  await r.pause();
  const previous = Object.getOwnPropertyDescriptors(r),
    originalFetch = window.fetch,
    files = r.backingFiles(),
    requests = [],
    select = r.ui.querySelector('[data-control="backing"]'),
    status = r.ui.querySelector("[data-status]"),
    button = (key) =>
      r.section.querySelector(`practice-audio[data-backing="${key}"] button`);
  for (const key of ["src", "drums", "drumless"])
    assert(files[key] && button(key), `Fixture lacks ${key}`);
  const samples = new Float32Array(8),
    buffer = (name) => ({
      name,
      duration: 60,
      length: 60 * 48000,
      sampleRate: 48000,
      numberOfChannels: 1,
      getChannelData: () => samples,
    }),
    response = (key) => {
      const bytes = new TextEncoder().encode(key);
      return new Response(bytes, {
        headers: { "Content-Length": String(bytes.length) },
      });
    };
  let fetchImpl = async (key) => response(key),
    scheduled = 0,
    finished = 0,
    started = 0;
  const blockedFetch = (gate, signal) => {
    signal.addEventListener(
      "abort",
      () => gate.reject(new DOMException("Superseded", "AbortError")),
      { once: true },
    );
    return gate.promise;
  };
  Object.assign(r, {
    selected: "src",
    backingKey: "src",
    backing: buffer("src"),
    backingInvalidated: false,
    pendingBacking: null,
    sourceChanged: false,
    mode: "playback",
    solo: false,
    playing: false,
    position: 0,
    duration: 60,
    passage: null,
    grid: null,
    track: { rate: 48000, length: 60 * 48000, segments: [], undo: null },
    ctx: {
      currentTime: 1,
      sampleRate: 48000,
      decodeAudioData: async (bytes) => buffer(new TextDecoder().decode(bytes)),
    },
    ready: async () => {},
    current: () => 1,
    tick() {},
    draw() {},
    player: () => null,
    schedule() { scheduled++; },
    rememberAudition() {},
    finishCapture: async () => { finished++; r.passage = null; },
    beginCapture() { started++; r.passage = { start: 48000 }; },
  });
  window.fetch = (url, options) => {
    const key = Object.keys(files).find((key) => files[key] === String(url));
    if (!key) return originalFetch(url, options);
    requests.push({ key, signal: options?.signal });
    return fetchImpl(key, options?.signal);
  };
  try {
    // Selection responds in the click handler, before initialization can finish.
    const ready = deferred();
    r.ready = () => ready.promise;
    button("drums").click();
    const first = r.queue;
    assert(select.value === "drums", "Dropdown waited for initialization");
    assert(button("drums").getAttribute("aria-pressed") === "true", "Button did not highlight immediately");
    assert(button("drums").getAttribute("aria-busy") === "true", "Loading button lacks busy state");
    assert(status.textContent.includes("Loading"), "Initialization wait has no loading message");
    assert(r.selected === "src", "Pending choice replaced the heard backing");
    let waveformText = "";
    r.drawBacking({ fillText: (text) => { waveformText = text; } }, null, 0, 60, 500, 80);
    assert(waveformText.includes("Loading"), "Waveform did not show the loading state");
    await Promise.resolve();
    assert(requests.length === 0, "Download ran before initialization finished");
    r.ready = async () => {};
    ready.resolve();
    await first;
    assert(r.selected === "drums" && r.backing.name === "drums", "First selection did not finish");

    // A repeated click reuses its request; a different choice cancels it.
    const download = deferred();
    fetchImpl = (key, signal) => key === "drumless"
      ? blockedFetch(download, signal)
      : Promise.resolve(response(key));
    r.playing = true;
    const old = r.requestBacking("drumless");
    await until(() => requests.at(-1)?.key === "drumless");
    const canceledSignal = requests.at(-1).signal,
      requestCount = requests.length;
    assert(r.requestBacking("drumless") === old, "Repeated choice started a new request");
    assert(requests.length === requestCount, "Repeated choice duplicated its download");
    assert(select.value === "drumless" && r.selected === "drums", "Download wait lost requested or heard selection");
    const latest = r.requestBacking("src");
    assert(canceledSignal.aborted, "New selection did not abort the old download");
    await latest;
    assert(r.selected === "src" && select.value === "src", "Superseded download won selection");
    assert(r.playing, "Canceled download paused existing playback");
    assert(!r.pendingBacking, "Successful selection stayed busy");
    r.playing = false;

    // Show real byte progress while the response body remains unfinished.
    let stream;
    fetchImpl = async () => new Response(new ReadableStream({
      start(controller) { stream = controller; streams.push(controller); },
    }), { headers: { "Content-Length": "8" } });
    const progressing = r.requestBacking("drumless");
    await until(() => !!stream);
    stream.enqueue(new TextEncoder().encode("drum"));
    await until(() => status.textContent.includes("50%"));
    assert(button("drumless").getAttribute("aria-busy") === "true", "Partial download cleared busy state");
    stream.enqueue(new TextEncoder().encode("less"));
    stream.close();
    await progressing;

    // Failures restore the heard choice and remain retryable without stopping it.
    const previousBuffer = r.backing;
    fetchImpl = async () => { throw Error("Synthetic network failure"); };
    r.playing = true;
    await r.requestBacking("drums");
    assert(r.selected === "drumless" && select.value === "drumless", "Failure did not restore selection");
    assert(r.backing === previousBuffer && r.playing, "Failed download changed existing audio");
    assert(!r.pendingBacking && status.textContent.includes("retry"), "Failure stayed busy or hid retry guidance");
    fetchImpl = async (key) => response(key);
    await r.requestBacking("drums");
    assert(r.selected === "drums", "Retry did not load backing");
    r.playing = false;

    // Pause stops immediately instead of waiting behind a pending download.
    const pauseDownload = deferred();
    fetchImpl = (key, signal) => blockedFetch(pauseDownload, signal);
    r.playing = true;
    const loadingAtPause = r.requestBacking("drumless");
    await until(() => requests.at(-1)?.key === "drumless");
    const pausedSignal = requests.at(-1).signal;
    r.ui.querySelector('[data-action="play"]').click();
    assert(!r.playing, "Pause waited for the pending backing download");
    assert(pausedSignal.aborted, "Pause left the pending download running");
    await loadingAtPause;
    assert(!r.playing && !r.pendingBacking && r.selected === "drums", "Canceled download changed state after Pause");
    fetchImpl = async (key) => response(key);

    // Clicking the loaded backing must not split an active recording passage.
    r.mode = "record";
    r.playing = true;
    r.passage = { start: 0 };
    const beforeNoop = { requests: requests.length, scheduled, finished, started };
    await r.requestBacking("drums");
    assert(requests.length === beforeNoop.requests, "Loaded backing downloaded again");
    assert(scheduled === beforeNoop.scheduled && finished === beforeNoop.finished && started === beforeNoop.started,
      "Loaded backing interrupted recording or rescheduled playback");
    r.mode = "playback";
    r.playing = false;
    r.passage = null;

    // Decoding cannot be aborted, but its late failure must not affect a new choice.
    const staleDecode = deferred();
    let decoding = false;
    r.ctx.decodeAudioData = async (bytes) => {
      const key = new TextDecoder().decode(bytes);
      if (key !== "src") return buffer(key);
      decoding = true;
      return staleDecode.promise;
    };
    r.playing = true;
    r.requestBacking("src");
    await until(() => decoding);
    const afterDecode = r.requestBacking("drumless");
    staleDecode.reject(Error("Synthetic stale decode failure"));
    await afterDecode;
    assert(r.selected === "drumless" && r.playing, "Stale decoder failure affected the latest backing");
    assert(!r.pendingBacking && !status.textContent.includes("retry"), "Stale decoder failure replaced success feedback");
    r.ctx.decodeAudioData = async (bytes) => buffer(new TextDecoder().decode(bytes));
    r.playing = false;

    // Home already in the queue may pause internally, but must keep a newer choice.
    const beforeHomeDownload = deferred(),
      beforeHome = requests.length;
    r.selected = r.backingKey = "src";
    r.backing = buffer("src");
    r.playing = true;
    fetchImpl = (key, signal) => key === "drumless"
      ? blockedFetch(beforeHomeDownload, signal)
      : Promise.resolve(response(key));
    r.requestBacking("drumless");
    await until(() => requests.length > beforeHome);
    r.ui.querySelector('[data-action="home"]').click();
    const chosenAfterHome = r.requestBacking("drums");
    await chosenAfterHome;
    assert(r.selected === "drums" && select.value === "drums", "Older Home canceled the newer backing choice");
    assert(r.position === 0 && r.playing, "Home failed to seek or resume playback");
    assert(requests.slice(beforeHome).map((q) => q.key).join() === "drumless,drums", "Home downloaded the wrong backing");
    r.playing = false;
    fetchImpl = async (key) => response(key);

    // An older Play waiting for ready must honor a newer requested choice.
    const playReady = deferred();
    let waitingForReady = false;
    r.selected = "src";
    r.backing = r.backingKey = null;
    r.ready = () => { waitingForReady = true; return playReady.promise; };
    const beforePlay = requests.length;
    r.run(() => r.play());
    await until(() => waitingForReady);
    const chosenAfterPlay = r.requestBacking("drumless");
    r.ready = async () => {};
    playReady.resolve();
    await chosenAfterPlay;
    assert(r.selected === "drumless" && r.playing, "Older Play discarded the newer choice");
    assert(requests.slice(beforePlay).map((q) => q.key).join() === "drumless", "Older Play loaded or reloaded the wrong backing");
    r.playing = false;

    // A request superseded while the capture tail drains must resume capture.
    const captureEntered = deferred(),
      captureTail = deferred(),
      nextDownload = deferred();
    r.selected = r.backingKey = "src";
    r.backing = buffer("src");
    r.mode = "record";
    r.playing = true;
    r.passage = { start: 0 };
    r.finishCapture = async () => {
      captureEntered.resolve();
      await captureTail.promise;
      r.passage = null;
    };
    fetchImpl = (key, signal) => key === "drumless"
      ? blockedFetch(nextDownload, signal)
      : Promise.resolve(response(key));
    const beforeCapture = started,
      draining = r.requestBacking("drums");
    await captureEntered.promise;
    r.requestBacking("drumless");
    captureTail.resolve();
    await draining;
    await until(() => requests.at(-1)?.key === "drumless");
    assert(started === beforeCapture + 1 && r.passage, "Superseded capture drain left recording inactive");
    assert(r.selected === "src" && r.playing, "Superseded capture drain changed heard backing");
    await r.requestBacking("src");

    return {
      immediateSelectionBeforeReady: true,
      loadingWaveform: true,
      repeatedRequestReused: true,
      latestSelectionWins: true,
      canceledRequestPreservesPlayback: true,
      downloadProgress: true,
      failureRollsBackAndRetries: true,
      pauseCancelsDownloadImmediately: true,
      loadedBackingDoesNotInterruptCapture: true,
      staleDecodeFailureIgnored: true,
      olderHomePreservesNewSelection: true,
      olderPlayHonorsNewSelection: true,
      supersededCaptureContinues: true,
    };
  } finally {
    r.cancelBacking();
    for (const stream of streams) {
      try { stream.close(); } catch {}
    }
    deferreds.forEach((gate) => gate.resolve());
    await r.queue;
    window.fetch = originalFetch;
    for (const key of Object.keys(r)) delete r[key];
    Object.defineProperties(r, previous);
    r.sync();
    r.draw();
  }
})();
