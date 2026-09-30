# Local drum recording implementation handoff

The feature is ready to start implementation. Begin with a small working recording
experiment to verify timing and passage replacement, then build out the complete
track. Hardware latency and mobile memory use have not been measured. The existing
research and the user's settled behavior are in
[local-recording-research.md](local-recording-research.md).

Continue in `/home/akaihola/prg/drum-transcribe-local-recording`, on branch
`research/local-recording`. The research is committed as `39e8387`, and the settled
requirements as `ab29343`. The original checkout at
`/home/akaihola/prg/drum-transcribe` is clean. No recording code has been written.
Read `AGENTS.md`, `CLAUDE.md`, `docs/webapp.md`, `docs/style-guide.md`, and
`docs/operations.md` before editing. Use Bash for commands, keep `SHELL` set to
Bash, and commit in small logical parts.

Implement one browser-local recording track per project version, shared across
that version's original, drums stem, without-drums accompaniment, and all three
sonification nodes. The user must be able to record while any selected backing
node plays, audition the local track mixed with any node, adjust the balance, and
hear the recording solo. Show the saved waveform, playhead, and recording range.
The local track and selected backing must share one song timeline.

These are the user's settled requirements:

- Mute, Play back, and Record can be selected at any position, both paused and
  playing. Mute preserves the recording. Record replaces only the passage crossed
  by the advancing playhead, including newly recorded silence, and leaves all
  samples outside that passage in place.
- Seeking disarms Record, including seeks through the waveform, player controls,
  score, or MuseScore integration.
- There is no live microphone echo. During recording, the user hears the selected
  backing. A separate calibration function may correct placement of captured
  audio if needed.
- Store the recording locally in the browser, never in the server's output tree
  or bucket. Preserve it across reloads whenever browser storage permits.
- Each version's recording track has a Clear button that starts over and frees
  storage. Remove recording samples, waveform data, undo history, and remembered
  audition state. Stop and disarm recording, release memory, and prevent pending
  writes from recreating cleared data. Keep other versions and pipeline results.
- Download always contains the whole song timeline and the latest edited local
  recording, using the final mix or solo settings actually heard. Moving controls
  while paused does not change the remembered audition. Listening with the local
  track muted is ignored. With no qualifying audition, download the recording
  solo. Remember the backing node as well as track levels.
- Master volume affects listening only, never download loudness. Recording input
  level is independent of listening balance.
- Downloads are importable locally. Import loads the finished audio as the local
  track, including any backing already mixed into it. Preserve its song-time-zero
  position, leading silence, and gaps. Do not apply microphone-delay compensation
  again. Ordinary audio files are sufficient; no restoration package is required.
  Solo playback hears an imported mix without adding another backing layer.

Use these implementation defaults unless the user changes them. They are proposed
defaults, not additional decisions already made by the user:

- Record selected while paused arms recording. Pressing Play begins writing at the
  current position. Pausing finishes the current passage and keeps Record armed;
  resuming continues from that position. Seeking still disarms it.
- At the end of the source song, finish the passage, stop playback, and disarm
  recording. Do not loop or extend the song. The source audio defines song length;
  pad shorter backing files with silence and bound longer derived tails to it.
- Omit a count-in from the first implementation. Start with foreground desktop
  Chromium and Firefox, a device microphone, and wired headphones. Check mobile
  support before claiming it works there.
- Export WAV initially. Import replaces the local track as a whole after decoding
  and validation succeed. Match shorter imports to the song with trailing silence;
  reject longer imports with a clear message instead of silently truncating them.
  Treat the import as an edit, preserving remembered audition settings.
- Offer Undo for the last passage replacement. Clear releases its undo data.

The first implementation step should prove the timing, not build the whole UI.
Serve a small integrated experiment that selects one backing file, obtains the
microphone, records raw samples, plays the resulting take against that backing,
and replaces a short passage in the middle. Use an adjustable capture offset;
measure whether browser estimates alone suffice or a separate click calibration
is necessary. Capture offset belongs to each take, so changing device settings
does not shift earlier correct passages. Never quantize the user's performance.

Use one `AudioContext` for backing and recorded playback, scheduled against its
audio clock. Capture with an `AudioWorklet`, recording frame positions as well as
samples. Keep waveform drawing, storage, and encoding off the audio-processing
path. Batch transfers to avoid per-block allocation and messaging overhead.
Prefer the smallest design that meets the timing requirement; do not introduce a
framework, heavy audio editor, or cross-origin isolation without evidence that it
is needed.

Keep the requested replacement interval distinct from the time captured samples
arrive. Output and input delay mean some valid samples arrive after the user stops
recording. Finish a bounded capture tail and place samples by their corrected song
positions, clipped to the requested interval. Do not shift an already-cut passage
over neighboring audio. Commit only valid capture; permission failure, a removed
microphone, or interrupted input must not silently erase the prior passage.

For this first experiment, verify repeatable alignment at the start and end of a
long take, and unchanged samples outside a replacement interval. The research
suggests a 10 ms alignment target after calibration on the chosen wired setup;
this is a target to measure, not a promised capability. Synthetic audio with known
onsets can verify scheduling and replacement automatically. A real microphone and
output path still need a separate measurement. Document that gap if hardware is
unavailable; do not claim synthetic tests establish device latency.

After the experiment works, continue through these logical increments:

1. Integrate the shared transport with all player nodes, mode switching, balance,
   solo, score following, and seek disarming. Preserve active audio state during
   live progress refreshes and version changes.
2. Add the waveform, input meter, Undo, browser persistence, and Clear. Use
   IndexedDB chunks and atomic updates to the replacement map. Persist the
   remembered audition alongside the recording. Allow only one writer per track
   across tabs, and detect when the backing source has changed.
3. Add full-song WAV download and import. Listening and download must use the same
   track gains and peak handling before the listening-only master gain. Encode
   locally; avoid complete recording copies for each edit and export when possible.
4. Check the complete behavior in the supported browsers, document limitations,
   and update the web app documentation and user help.

Relevant integration points are in `src/drum_transcribe/serve.py`: `YtAudio`,
`MEDIA`, `versionPieces`, `setVolume`, `refreshVersion`, `lastAudio`, `seekToBar`,
the score-follow listeners, and MuseScore seek polling. Current media elements
own their playback positions; practice playback must instead follow the shared
transport. Do not play a native element and a decoded copy of it simultaneously.
Microphone capture must not connect to the speaker destination.

YouTube original nodes currently play an iframe. For recording and mixed playback,
use the already-downloaded `v.source` audio; the iframe cannot provide samples for
download. Check its timing against the other backing files. The current `/static/`
route allows only two specific image files. If adding audio modules or a worklet,
extend that route with explicit, bounded asset paths and appropriate content types.
Do not introduce an arbitrary filesystem-serving route.

Recording requires HTTPS or localhost. The server can remain bound to `0.0.0.0`,
but ordinary HTTP access from another device does not grant microphone access.
Use a trusted HTTPS address for remote-device recording tests. A local recording
on the cloud site's HTTPS origin still stays in that browser. Different origins,
ports, and browser profiles have separate recordings. Explain storage failures
without discarding the in-memory take or pretending it was saved.

Run the worktree server on a separate port, such as 8766, so the existing systemd
service on 8765 keeps running. Cached song files and the existing Python environment
are in the original checkout; ignored data is absent from the new worktree. A
lightweight way to serve the new code against existing results is:

```bash
cd /home/akaihola/prg/drum-transcribe-local-recording
export SHELL="$(command -v bash)"
PYTHONPATH="$PWD/src" /home/akaihola/prg/drum-transcribe/.venv/bin/python \
  -m drum_transcribe.cli serve /home/akaihola/prg/drum-transcribe/output \
  --host 0.0.0.0 --port 8766
```

That command is provided for the next step; it has not been run. Treat the shared
output as fixtures when testing the recording feature. Serve a copied fixture tree
if testing server-side edits. Do not restart the production service to test this
worktree: its unit still points to the original checkout. Consult operations.md
before changing deployment or network access. Prefer T3 preview tools when
available; otherwise follow the PinchTab skill for browser testing.

Before calling the feature complete, verify:

- Record over 00:40 through 00:46; earlier and later samples stay unchanged, and
  Undo restores the replaced passage. Switch modes both paused and playing.
- Every seek disarms Record. Playback and recording stop together at song end or
  an audio interruption. Capture tails cannot overwrite another seek destination.
- Audition one mix, mute the recording, play another backing, then download. It
  still uses the last qualifying mix. Edit afterward and download again; it uses
  the latest track with that remembered mix. Changes made while paused are ignored.
- Export with different master volumes yields the same decoded file samples. The
  file always spans the source song, regardless of the listened passage or cursor.
- Download then import a solo and a finished mix. Their positions and leading gaps
  survive, and imported audio receives no additional capture offset.
- Reload restores track and audition state. Clear removes their storage and undo
  data, including after pending writes settle. Another version remains intact.
- Permission denial, missing microphone, insufficient storage, and multiple tabs
  preserve valid work and give useful feedback. Network inspection shows no
  microphone audio sent to any API or bucket.
- Existing native playback, source switching, score seeking, bar highlighting,
  shared volume, and live progress refresh still work. Measure memory and export
  behavior on a long song before claiming mobile support.

Report what was implemented, the timing and memory evidence, browser coverage,
remaining limitations, and commits. Update this handoff and the research if the
experiment changes the technical approach. Keep the user's settled behavior intact.
