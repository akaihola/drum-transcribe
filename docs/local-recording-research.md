# Browser-local drum recording research

Researched 2026-09-30. This assessment records the agreed behavior and proposed
technical approach. Browser documentation and the current player code were
inspected. No microphone or hardware latency measurements were made.
The next step, implementation defaults, and acceptance checks are in
[local-recording-handoff.md](local-recording-handoff.md).

The requested recording track is feasible in current browsers. The work goes
beyond adding a record button: accurate replacement of short passages needs a
shared audio timeline, recording-delay compensation, and a precise definition of
what the download contains. Microphone audio, edits, waveform data, and mix settings
can stay entirely on the device. No recording upload endpoint or bucket object is
needed.

The user confirmed that live microphone echo is unnecessary. Record mode therefore
plays the backing only, with an input meter and waveform providing recording
feedback. A separate latency-calibration function can be added to the UI if needed.

The existing app has a useful starting point. `serve.py` already exposes source
audio, drums, accompaniment without drums, and the three sonifications per version.
It also has a shared volume control, score seeking, and bar highlighting. I would
add one local track per project version, shared by all of that version's player
nodes. A take recorded against the accompaniment could then be auditioned against
the original or a sonification without making another copy of the take.

There are two integration constraints in the current code:

- Each player owns its playback position. Starting two players together does not
  establish the timing guarantees needed for recording and mixing. Practice mode
  should have one transport, meaning one playhead and one play/pause state, with
  one selected backing node.
- YouTube originals use a cross-origin iframe, wrapped by `YtAudio`. Its documented
  API exposes playback controls and time queries, but no audio samples or Web Audio
  connection. It cannot supply audio for an offline mix. For recording and mixed
  listening, that original node would need to use the downloaded `v.source` audio
  already available in the app. The timing must match that file, including any
  differences from the embedded video. This limitation follows from the
  [YouTube iframe API](https://developers.google.com/youtube/iframe_api_reference).

A suitable audio design would decode only the selected backing file, play it and
the local track through the same `AudioContext`, and capture microphone samples
through an `AudioWorklet`. Store the original microphone samples independently
of listening volume. Capture sample-frame positions, not the arrival time of a
JavaScript callback. Waveform drawing and browser-storage writes can happen in
batches away from audio processing. The
[Web Audio specification](https://www.w3.org/TR/webaudio-1.0/) defines the common
audio clock, scheduled sources, and worklet frame positions.

`MediaRecorder` is useful for a simple voice-recorder-style feature, but I would
not choose its encoded chunks as the editable timeline for this requirement.
Chunk delivery intervals are not exact, and background or screen-lock behavior
can delay them. Encoded chunks need decoding and trimming before precise edits.
An `AudioWorklet` captures raw samples directly. See
[MediaRecorder chunk timing](https://developer.mozilla.org/en-US/docs/Web/API/MediaRecorder/dataavailable_event)
and [AudioWorklet processing](https://developer.mozilla.org/en-US/docs/Web/API/AudioWorkletProcessor/process).

The proposed meanings of the three track modes are:

| Local track mode | Transport paused | Transport playing |
| --- | --- | --- |
| Mute | Keep all audio and the selected position | Backing plays; local track is silent; no replacement |
| Play back | Ready to audition from the selected position | Local track plays in sync; backing can be mixed in or silenced for solo |
| Record | Arm recording at the selected position; write nothing until transport starts | Capture the microphone and replace only the passage crossed by the playhead |

Record while paused cannot both freeze the song position and write a progressing
performance onto it. Arming until Play is pressed is my proposed interpretation.
Another possible choice is for Record to start the transport automatically.

Switching from Play back to Record during playback starts a replacement passage.
Switching back ends it. The prior local audio is silent during replacement.
There is no live microphone playback. Muting the local track should never erase it.

For example, replacing 00:40 through 00:46 leaves everything before 00:40 and after
00:46 at its original position. It does not insert six seconds or shift the rest
of the performance. Newly recorded silence also replaces old audio in that range.
Missing input caused by a device failure should not silently erase the old take.
Keep old passages until valid capture is committed, and offer Undo for the last
replacement. Small edge fades may prevent clicks, but their extent must be bounded
and should not blur drum attacks or change audio outside the replacement range.

Seeking disarms Record, including seeking while paused and external MuseScore
seeks. Finish any active replacement interval before moving the playhead. Pausing
ends the current replacement interval. Changing project version should also end
recording and disarm it under the proposed default.
The existing MuseScore polling interval of one second is suitable for navigation,
not precision timing or punching into a passage.

Latency has several different effects, and each needs separate treatment:

| Delay | Consequence | Proposed treatment |
| --- | --- | --- |
| Backing output delay | Audio leaves the browser before you hear it | Account for actual output timing when placing the take |
| Microphone input delay | A hit reaches the browser after it happened | Place captured samples earlier by the measured effective offset |
| Control and display delay | A button, waveform, or highlighted bar can lag the audio | Drive audio from its sample clock; draw visuals separately |
| Buffering or interruptions | Playback and recording may stop advancing together | End the take safely and preserve valid audio; never let one timeline run ahead |

Suppose the backing takes 35 ms to reach the headphones and a microphone hit takes
25 ms to reach the audio graph. A player matching the sound they hear can appear
roughly 60 ms late on the browser's uncorrected timeline. These are illustrative
numbers, not measurements of this laptop. The correction should remove the device
offset, while preserving the musician's real timing. Snapping hits to the beat or
automatically aligning each take to the original drums would hide the performance
we want to hear.

The browser exposes useful estimates: `baseLatency` covers delivery from the audio
graph to the host audio system, `outputLatency` estimates the hardware output
delay, and `getOutputTimestamp()` relates the output position to the performance
clock. These are not interchangeable measurements. A low-latency request is a
hint the browser may ignore. Microphone `getSettings().latency` has limited browser
availability and is only an estimate. See
[base latency](https://developer.mozilla.org/en-US/docs/Web/API/AudioContext/baseLatency),
[output latency](https://developer.mozilla.org/en-US/docs/Web/API/AudioContext/outputLatency),
[output timestamps](https://developer.mozilla.org/en-US/docs/Web/API/AudioContext/getOutputTimestamp),
and [microphone latency](https://developer.mozilla.org/en-US/docs/Web/API/MediaTrackSettings/latency).

The separate calibration UI could record a known emitted click sequence and
measure its return, followed by an adjustable earlier/later correction. Acoustic
calibration includes speaker-to-microphone travel; electrical loopback measures a
different path. The calibration path must represent the recording setup closely
enough, or the remaining error needs manual adjustment. A human tapping to a click
is less reliable because it mixes device delay with human timing.

Record the compensation used for each take. Recalibrate after changing microphone,
output device, audio route, or processing settings. Otherwise changing today's
offset could accidentally shift yesterday's correct passages. Test long takes for
drift as well as a constant offset; shared playback scheduling cannot by itself
prove that every hardware capture path stays aligned.

Delay compensation also affects replacement boundaries. Samples corresponding to
the end of the requested passage may arrive after the user leaves Record. The
implementation needs a short capture tail and must commit samples according to
their corrected song positions. It must not shift an already-cut passage earlier
and thereby overwrite neighboring audio. Any temporary microphone buffering should
be bounded, disclosed, and discarded when no longer needed.

A usual 128-frame audio-processing block at 48 kHz lasts about 2.67 ms. That is only
one part of the path, not a promise of 2.67 ms total latency. Do not hardcode the
block length. See [worklet block sizes](https://developer.mozilla.org/en-US/docs/Web/API/AudioWorkletProcessor/process).
For a first prototype, I would aim for repeatable alignment within 10 ms after
calibration on the chosen wired setup. That is an acceptance target to measure,
not an established capability of the app. With live microphone echo excluded,
the main latency test is how accurately the saved take aligns during playback.

Wired headphones are the preferred practice setup. They also keep backing audio
out of the microphone. Bluetooth routes need separate measurement and can change
when a headset microphone opens. Apple documents reduced playback quality in that
case in [Bluetooth headphone microphone behavior](https://support.apple.com/en-us/102217).
A laptop microphone plus wired headphones is a reasonable initial target. A loud
acoustic kit may overload a built-in microphone before software receives the
signal; a meter can reveal clipping, but cannot repair it afterward.

Request music-oriented capture with echo cancellation, automatic gain control,
and noise suppression disabled, and verify which settings the browser actually
applied. Speech processing can alter attacks, cymbal decay, and dynamics. Some
sources cannot disable particular processing. These controls and their capability
reporting are defined in [Media Capture and Streams](https://www.w3.org/TR/mediacapture-streams/).
Using speakers instead of headphones captures backing leakage; disabling speech
processing does not remove that leakage.

The browser must grant microphone permission. Recording requires a secure page:
HTTPS works, and the browser treats localhost as a special trusted case. A phone
opening the laptop over an ordinary `http://LAN-address:8765` connection will not
have the same microphone access. The HTTPS cloud site can still record entirely
locally. No cloud audio processing is needed. See
[microphone access requirements](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia).

Browser-local persistence should use IndexedDB, with recordings identified by
project, version, and a source identity strong enough to detect changed audio.
Keep samples in chunks and store the replacement map, waveform peaks, and take
offsets alongside them. Recordings should survive reloads whenever browser storage
allows it. Persist the remembered audition settings with the track so reloads also
preserve download behavior. An interrupted edit should leave either the prior
passage or the complete committed replacement. A small canvas waveform showing
recorded passages, empty regions, playhead, and active replacement range would be
enough to start. Use min/max peaks so narrow drum attacks remain visible, and allow
seeking without forcing a bar boundary. A live input oscilloscope alone would not
show the saved song-length track.

Local storage belongs to one browser profile and one website origin, including
scheme, hostname, and port. Laptop localhost and the cloud hostname therefore
have separate recordings. Private browsing and clearing site data can remove
them. Browsers can evict ordinary stored data; persistent storage can be requested
but is not guaranteed to be granted. Show whether a take is saved locally and make
download easy. See [browser storage and eviction](https://developer.mozilla.org/en-US/docs/Web/API/Storage_API/Storage_quotas_and_eviction_criteria).
Do not put microphone samples in API requests, server logs, pipeline output, or
bucket uploads. The current CDN-loaded scripts run in the page's origin; avoiding
uploads is an application behavior, not isolation from all scripts in that page.

Each project version's local recording track must have a Clear button for starting
over and freeing storage. It should end any active recording, disarm Record, and
delete that track's stored samples, edit history, waveform data, and remembered
audition. Release its in-memory buffers and file references as well. Retaining the
old take for Undo would defeat Clear's storage-freeing purpose. The next recording
starts with the solo-download default. Clearing this local track must not delete
the song version, backing audio, or transcription results.

Memory matters more than the compressed file sizes suggest. At 48 kHz, ten minutes
of mono float32 capture is 115.2 MB, and a stereo decoded backing is 230.4 MB.
Undo copies, an offline-rendered stereo mix, and the download buffer add more.
Decode the selected backing only, avoid complete copies for each punch, and
measure export memory on phones. The arithmetic is sample rate multiplied by
duration, channels, and bytes per sample. Decoding uses complete file data and
resamples to the context rate, as documented in
[decodeAudioData](https://developer.mozilla.org/en-US/docs/Web/API/BaseAudioContext/decodeAudioData).
Test actual MP3, FLAC, and Ogg/Opus artifacts in each target browser. Their starts,
channel layouts, durations, and tails must agree with the shared song timeline.

The download should be rendered locally from the backing and edited microphone
samples, rather than capturing the speaker output in real time. `OfflineAudioContext`
can render a graph to an audio buffer without waiting for a whole song to play;
simple mixing can also be done in chunks in a worker to control memory. A WAV
download is a sensible first format. Mono 16-bit WAV at 48 kHz is 57.6 MB per ten
minutes; stereo is 115.2 MB. See
[offline audio rendering](https://developer.mozilla.org/en-US/docs/Web/API/OfflineAudioContext).

The user settled the export behavior:

- Remember the final balance actually heard, including the backing node identity,
  backing and recording gains, and solo state. Moving controls while paused does
  not change these remembered settings. Balance changes during playback update
  the final heard settings; export does not reproduce their history over time.
- Listening with the recording muted is ignored. It does not replace the previous
  remembered mix or solo. Before any qualifying audition, download the recording
  solo.
- After editing, download the latest recording with those remembered mix settings.
  Export does not preserve an older audio revision. Use the latest track's stored
  passage timing and compensation when rendering it.
- Always download the whole song timeline, including leading silence and gaps.
  The current playhead position and listened passage do not crop the file.
- Master volume controls listening only and must not affect file loudness. Apply
  the remembered track levels before the master-volume stage. Hardware headphone
  volume also has no effect on the file.

Use the same track-mixing rules for listening and export, including peak protection
if present, before the listening-only master gain. Do not normalize only the
download. Independent backing and recording levels should support both solo
endpoints and ordinary balance adjustment. Input gain must stay separate from
listening balance.

Downloads must be importable into a local recording track, without uploading them.
The user chose to load the finished audio as the recording track, including any
backing already mixed into it. Import places it at song time zero and preserves
leading silence and gaps. Already aligned imported samples should not receive
microphone latency compensation again. The waveform and passage replacement
operate on this combined audio. Replacing part of an imported mix therefore
replaces both the previous drums and the baked-in backing in that interval.
Solo playback hears the imported mix as downloaded; mixing in a player node adds
that player's audio to the backing already present in the imported track.
The download can remain an ordinary audio file with no separate restoration data.

The implementation handoff proposes defaults for the remaining small choices:
Record while paused arms until Play is pressed, song end stops and disarms
recording, and the first implementation omits a count-in. These defaults allow
implementation to start and remain open to user changes.

Test microphone permission denial, unplugged devices, storage exhaustion,
multiple tabs editing the same track, source replacement, and browser interruption.
Only one tab should write a given track at a time. Pause/disarm on unsafe audio
interruptions rather than silently resuming replacement. Mobile operating systems
can interrupt audio during calls, app switches, or screen locking; the
[audio context state documentation](https://developer.mozilla.org/en-US/docs/Web/API/BaseAudioContext/state)
describes these interruptions. Treat foreground recording as the initial supported
case unless actual device tests establish more.

Also verify persistence through reload, muted listening preserving the remembered
mix, edits using the latest take with the prior mix, and identical export loudness
at different master volumes. Check full-song download/import timing and that Clear
removes stored track data, including undo data, and cannot be undone by a late
storage write from the recording that was just stopped.

Before committing to the full design, build a narrow experiment with one backing
file, microphone capture, calibrated placement, and replacement of a short middle
passage. Measure onset alignment at both ends of a long take, verify that untouched
samples stay unchanged, and compare the decoded exported mix against the audition
render. Then check player switching, paused mode changes, score seeking, live UI
refresh, and the intended desktop and mobile browsers. This experiment would
resolve the main timing and memory uncertainties without building the whole
interface first.
