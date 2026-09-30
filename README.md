# drum-transcribe

Turns a music recording into drum sheet music, automatically. Every
intermediate result is saved so mistakes can be found, heard, and fixed.

## What it does, step by step

1. **Isolate the drums.** A neural network ([Demucs][demucs]) separates the drum kit
   from the rest of the music, producing a "drums stem" — the same recording
   with only the drums audible. It also saves the rest of the band as a
   **without-drums track** for playing along on your own kit.
2. **Find the beat.** Another model ([beat_this][beat-this]) marks every beat and every
   bar line (downbeat) in time, like a conductor tapping along. The model
   sometimes stumbles for a stretch — doubling the tempo or hearing a bar
   line on every beat — so if it produced bars of unequal length, the bar
   lines are straightened automatically to the piece's usual bar length.
   (A meter switch above the score turns this off for pieces that genuinely
   change meter.)
3. **Detect the hits.** Each drum hit is located and named: kick, snare,
   tom, hi-hat, cymbal. Two alternative methods are available — see
   [*Pipeline variants*][pipeline-variants] below.
4. **Estimate loudness.** Each hit's strength becomes a MIDI velocity, so
   quiet "ghost notes" survive into the notation.
5. **Snap to the grid.** Hits are placed on the beat grid (16ths, 32nds, or
   triplets, chosen per beat). How far each hit had to move is recorded —
   large moves are a warning sign.
6. **Write the score.** The result is saved as MusicXML and, when
   [MuseScore][musescore] is available, as a ready MuseScore file
   (`score.mscz`).

## Pipeline variants

Results of different methods are kept side by side, never mixed:

- **adtof** — a neural network ([ADTOF][adtof]) trained on real drum recordings reads the
  drums stem directly. Most accurate hit detection, but hears only 5
  categories (ride and crash cymbals are one "cymbal").
- **mdx23c** — the drums stem is first split further into six per-drum
  recordings (kick / snare / toms / hi-hat / ride / crash) by the MDX23C
  DrumSep model (run with [audio-separator][audio-separator]); hits are then
  detected in each one separately. Distinguishes ride from crash, but
  hears too many hits (leakage between the six recordings).
- **fused** — the best of both: adtof decides *when and what* was hit,
  and the six per-drum recordings are used only to tell ride from crash
  and to judge how hard each hit was.

## What is the sonification?

`sonification.ogg` is the original recording (at half volume) with a short
synthetic **blip added at every hit the computer transcribed**: a low thump
for kick, a noisy mid snap for snare, high ticks for hi-hat and cymbals.
Listening to it is the fastest way to check the transcription: a missing
blip = missed hit, a blip with no drum under it = false detection, the wrong
blip sound = wrong drum. No musical training needed.

## The web app

```bash
uv run drum-transcribe serve
```

Open `http://<the machine's address>:8765/` from any of your machines.

The same site also runs in the cloud at <https://plokkaus.vempai.men/>, so
it works even when the laptop is off. There you can listen and review
everything, and also add new pieces or versions — as an upload or a direct
audio link (YouTube and Google Drive links only work on the laptop, and so
do links to your own machines at home — the cloud site fetches only links
that anyone on the internet could open) — as
long as you tick "process on a rented cloud GPU". Keep the page open while
it processes. The cloud site sleeps when nobody uses it: the first visit
after a quiet period shows a "Starting up…" page for up to a minute, which
switches to the real page by itself. Files uploaded to the cloud site can
be at most 100 MB.

Because the cloud site is open to the whole internet, anyone may listen and
read there, but it only accepts a few new pieces per day from unknown
visitors, and *changing* anything — writing feedback, switching the meter,
deleting a version — needs a password. If it asks for one, ask Antti — after typing it once, that
browser is remembered and never asks again. The laptop site never asks.

**Main page**: your projects, plus a form to transcribe a new piece — upload
a sound or video file, or paste a public link (YouTube, a Google Drive share
link, or a direct URL). Submitting creates the project page and starts all
pipelines in the background; the project page shows their progress live.

**Project page**: one piece, with every uploaded/linked version of it (say,
the backing track and the album recording) in its own tab. Each tab has its
own address, so a link or bookmark opens that version directly. Another
version for comparison is added with the "+ add a version" tab; once
submitted, the new version's tab opens. Per version:

- players for the **original**, the **drums stem**, and each pipeline's
  **sonification**, laid out as a diagram whose arrows show what is made
  from what; one **volume** slider (top right) sets the volume of all of
  them. With local recording available, each box has a **Use as backing**
  button instead of its own player: it chooses what the recording panel
  below the diagram plays (see [Record your own drums](#record-your-own-drums-in-the-browser)).
  The original uses the downloaded audio, including for YouTube links.
  Where local recording is unavailable, each box keeps its own player, and
  a YouTube original plays in YouTube's player. A progress bar appears until
  the audio is ready;
- a **without drums** player above the score, with a **Download FLAC** link.
  FLAC compresses audio without losing quality. The stereo, 24-bit track
  plays on Android and imports into Ableton Live. It has the same timing as
  the original, so you can click a bar in the score to start there after
  choosing this player. Separation can leave some drums audible. Older
  versions get this track when their pipeline runs again;
- while any player plays, the **bar being heard is highlighted in teal** in
  the scores;
- **tap or click anywhere in a bar**, including a note or rest, and the
  recording plays from that bar when the comment switch is off;
- a **meter switch** above the score, showing the detected time signature:
  by default the bar lines are straightened automatically; choose the
  changing-meter option only if the piece really changes meter, and the
  scores are recomputed with the bar lines exactly as detected;
- **downloadable files** as small icons beside each sonification player — click
  to download or drag into your file manager: MusicXML (opens directly in
  MuseScore), MIDI, the raw detection data (JSON), and a ready MuseScore
  file. A red "!" on the MuseScore icon means MuseScore found bars that
  don't add up (e.g. after a badly detected beat) and saved the file
  anyway; hover over the icon to see which bars may look wrong;
- the pipelines' **scores rendered on the page**, chosen with the selector
  above the score;
- a **progress bar** in place of anything not ready yet, saying what is
  being done and roughly how long is left; a hatched, empty bar is waiting
  its turn. Point at a bar to see the estimated percentage — an estimate
  from how long each step usually takes, not an exact measurement. With
  the cloud GPU option, an extra bar at the top shows the rented machine
  starting up (usually 2–5 minutes). Results swap in by themselves as they
  finish, without reloading. The **pipeline log** is behind the gear
  button (top right);
- **feedback on the notation**: turn on **Comment on symbols** above the
  score, then tap a note or rest to comment on it, or empty staff space to
  comment on the whole bar. This can flag extra or missing notes, wrong
  rhythm, drum or time signature, or take free text. Commenting touches
  never start playback. With a mouse, right-click reverses the action:
  comment when the switch is off, play from the bar when it is on. Saved
  symbol comments tint the symbol orange; bar comments tint its barlines.
  Hover to read a comment, or use the commenting action again to edit or
  remove it. Commenting on the score title takes general feedback.
  The switch applies across score and version tabs during the page visit;
  reloading starts in playback mode. Everything is saved in the variant's
  `feedback.json`;
- a **Delete this version** button at the bottom, which removes the version
  and all its results for good (it asks first, and waits until processing
  has finished);
- a **"?" help button** on every page opens illustrated instructions.

## Record your own drums in the browser

Each version can have one drum track of your own, recorded in the browser.
On the laptop, open the app at [localhost:8765](http://localhost:8765/). The
cloud site does not offer recording yet.

Use desktop Chromium or Firefox, a device microphone and wired headphones.
Recording needs localhost or a trusted HTTPS address. Ordinary HTTP from
another machine keeps the original players available but cannot record.

The recording panel sits under the diagram. It works like the arrange window
of a recording program (a DAW): a bar with the buttons on top, a ruler with
bar numbers, and one lane for the backing and one for your drums.

- **Top bar**: ⏮ goes back to the start, ▶ plays and pauses, ● records. The
  counter shows the bar and beat (`17.3` is bar 17, beat 3) and the time.
  ↶ undoes the last recorded passage. **Whole song** shows the entire song;
  **Follow 16 bars** zooms in around the playhead. The status line says what
  you hear, or what ▶ will do next. The ⋯ button opens Export, Import,
  Latency correction and Clear.
- **Bars ruler**: click it, or either lane, to jump to that point.
- **Backing** lane: what you play along to. Choose it in the lane or with
  **Use as backing** in the diagram: the original, the track without drums,
  the drums stem, or a sonification. You can switch while it plays. The
  slider sets its level in decibels (0 dB leaves it unchanged, −6 dB is about
  half as loud); the bar at the right edge is its level meter.
- **Your drums** lane: your recording. Each recorded passage is a block
  labelled with its bars. ● arms recording, **M** mutes your track, **S**
  (solo) plays your track alone. The first slider is your track's level;
  **mic** is how strongly the microphone is recorded. The meter at the right
  shows the microphone while recording is armed. **CLIP** lights red when the
  microphone overloads: lower the mic slider and click CLIP to reset it.

Keyboard shortcuts: Space plays and pauses, R records, M mutes, S solos,
Home goes back to the start, Ctrl+Z undoes the last passage.

**Recording.** Press ● and then ▶ (or R, then Space). Playback starts two
bars before the playhead so you can find the groove; recording starts exactly
at the playhead. Where those two bars would reach back before the song
starts, metronome clicks fill the gap, so recording from the very beginning
gives you a two-bar count-in. Pressing ● while the song plays starts
recording at once (punching in); pressing it again stops recording and the
song keeps playing (punching out). Pause keeps recording armed for the next
▶. Jumping anywhere else stops recording, and your track plays back again.
The song's end stops both. You hear the backing, not the microphone.

Recording replaces only the passage the playhead crosses, silence included:
recording bars 17 to 20 leaves everything before and after in place. ↶
restores the last replaced passage during this visit.

**Export WAV** (in the ⋯ menu) always saves the whole song. It uses your
latest recording with the mix you last listened to: the backing you chose and
both levels, or your track alone if you last listened with Solo. The menu
shows that mix. Changing sliders while paused, or listening with your track
muted, does not change it. Before you have listened to your track with a
backing, the file has your track alone. The volume slider at the top right
only changes how loud you hear things, never the file.

**Import audio** loads an ordinary mono or stereo audio file as your track,
starting at 0:00 and keeping leading silence and gaps. Short files get
silence at the end; files longer than the song are refused without changing
your track. An imported finished mix keeps its backing inside your track, so
use Solo to hear it by itself. Imported audio gets no latency correction.

Your track and remembered mix stay in this browser when storage permits.
Nothing is uploaded or added to transcription results. Another browser profile,
address or port has separate recordings. Export a copy before relying on
browser storage. Only one tab can edit a version; close that tab and reload
another to transfer editing. **Clear your track** asks first, then removes
this version's audio, Undo and remembered mix, including pending writes. Other
versions and pipeline results stay intact.

**Latency correction** (in the ⋯ menu) places new microphone samples earlier on the song timeline.
Its **60 ms default is an unmeasured starting guess**. It belongs to each take,
so adjusting it never shifts older passages. Check it with a known click or
loopback recording on your own wired setup. The temporary microphone buffer
holds at most 171 ms and discards samples outside the requested passage.
Software timing passed the checks in Chromium and Firefox. Physical microphone
and headphone latency, mobile behavior and the HTTPS cloud path still need
measurement. [The implementation notes](docs/local-recording-handoff.md#implementation-results)
record the timing and memory evidence.

## Playing the recording from inside MuseScore

While editing a score in MuseScore, you can hear the original recording from
any spot: click a note in some bar and press the plugin's keyboard shortcut —
the recording plays from that bar in the browser tab where you have the
piece's project page open. The same shortcut also pauses: press it again
with the same bar selected, or select another bar to jump there while it
plays. (The browser needs one manual press of play after each page reload
before it lets the plugin start playback.)

One-time setup: the plugin (`musescore/PlayFromBar.qml`, already copied to
MuseScore's plugin folder on this laptop) must be enabled in MuseScore under
Home → Plugins → "Play/pause from bar", and given a shortcut via its ⚙
settings. If the web app ever runs on a different machine, change the
server address inside MuseScore: run the plugin with nothing selected
(click an empty spot first) and a small window opens where you can type
the new address and press Save. The same window appears by itself if the
plugin can't reach the server. (The address is stored in
`drum-transcribe.ini` next to the plugin, editable by hand too.)

## Running a transcription from the command line

```bash
uv sync                                          # once, installs everything
uv run drum-transcribe run song.mp3              # adtof variant (default)
uv run drum-transcribe run song.mp3 --variant mdx23c
uv run drum-transcribe run song.mp3 --variant fused
```

(The commands use [uv][uv], a free tool that downloads everything the
project needs the first time it runs.)

Results land in `output/<project>/<version>/<variant>/`; the source
recording, beat grid, drums stem and without-drums track are shared per
version. Everything runs on a normal CPU; a 3-minute song takes a few minutes
with adtof, while
mdx23c is much slower (roughly 10× the song length).

For the slow mdx23c processing there is a shortcut: the same pipeline can
run on a rented cloud graphics card, which turns half an hour of waiting
into a couple of minutes and costs two or three cents per song. In the web
app, just tick "process on a rented cloud GPU" when starting a
transcription; the results appear in the same places and look exactly the
same. Setting up the GPU machinery is a developer task — see
[`docs/gpu-workers.md`][gpu-workers].

## Honest limitations

Even the best available models mishear some things: toms are the weakest
category, hi-hat vs. ride gets confused, and flams, chokes, and open/closed
hi-hat are not detected at all. Every score needs a human check — that is
what the review website and the sonification are for. Details and the full
tool survey: [`docs/adt-landscape.md`][adt-landscape].

The [ADTOF][adtof] model weights are licensed for non-commercial use.

Developer/agent documentation starts at [`AGENTS.md`][agents]; deeper topics
live under [`docs/`][docs].

[adtof]: https://github.com/xavriley/ADTOF-pytorch
[adt-landscape]: docs/adt-landscape.md
[agents]: AGENTS.md
[audio-separator]: https://github.com/nomadkaraoke/python-audio-separator
[beat-this]: https://github.com/CPJKU/beat_this
[demucs]: https://github.com/adefossez/demucs
[docs]: docs/
[gpu-workers]: docs/gpu-workers.md
[musescore]: https://musescore.org/
[pipeline-variants]: #pipeline-variants
[uv]: https://docs.astral.sh/uv/
