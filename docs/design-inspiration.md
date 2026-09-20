# Design inspiration for the web app

Research notes (September 2026) on musicians' web apps that people love for
their look and feel. The goal: pick a visual style and interaction habits for
our own review pages (uploading a song, listening to the sonification,
correcting drum hits).

## The apps people love, and why

### [Soundslice](https://www.soundslice.com/) — closest to what we do

Interactive sheet music synced to real audio. The notation scrolls and a
cursor highlights exactly what you hear, and it reflows to fit any screen
size. Widely praised since launch ([Hacker News front page for a day][ss-hn],
[player redesign notes][ss-redesign]).

What to copy:

- **Notation and sound are one thing.** Click a bar → playback jumps there.
  The playing note is always highlighted.
- Vertical scrolling notation that fits the window, instead of a fixed
  page image.
- Clean, mostly monochrome interface: black notation on white, one accent
  color, controls hidden until needed.

### [Moises](https://moises.ai/) — the polished "musician's app" benchmark

Stem separation and practice tools; Apple Design Award finalist 2025 and
iPad App of the Year 2024. Reviews single out its
[minimal black-plus-one-accent-color look and large obvious buttons][moises-rev].

What to copy:

- **Few, large controls** designed for someone holding an instrument, not a
  mouse-precise office worker.
- One strong accent color on a calm dark or neutral background.
- Waveform strip as the main "where am I in the song" element.

### [Ableton Learning Music](https://learningmusic.ableton.com/) / [Learning Synths](https://learningsynths.ableton.com/)

Free interactive lessons that run in the browser; regularly cited as some of
the best-designed music sites ever made ([overview][ableton-blog]).

What to copy:

- **Flat, friendly, almost toy-like**: soft solid colors, rounded shapes, no
  gradients or shadows, generous empty space.
- Everything on screen is playable — you learn by poking at it, not by
  reading a manual.
- One idea per screen. No dashboards.

### [Chrome Music Lab – Song Maker](https://musiclab.chromeexperiments.com/Song-Maker)

Google's colored-grid sequencer, loved for being usable by children yet
useful for real sketching ([review][cml-rev]). Rows are pitch, columns are
time, click a square to place a note.

What to copy:

- The **grid metaphor for editing hits in time** — directly applicable to
  correcting drum hits: rows = drums (kick, snare, hi-hat…), columns = time,
  click to toggle.
- Bright color per row/instrument, so you can read the pattern at a glance.

### [Groove Pizza](https://www.musedlab.org/groovepizza/) (NYU MusEDLab)

Circular drum sequencer; drums arranged as pizza slices. Praised by the
Washington Post and USA Today, hundreds of thousands of users
([project page][gp-page]). Shows how playful a drum-editing interface can be
while staying precise.

### [Songsterr](https://www.songsterr.com/) and [Chordify](https://chordify.net/)

Play-along tab/chord sites musicians praise for one thing: **zero friction**
— find song, press play, follow the moving highlight
([Songsterr review][songsterr-rev], [Chordify review][chordify-rev]).
The lesson: the default screen should already be playing/showing the result;
options come later.

## Style direction distilled for us

1. **Flat, calm, friendly.** White or near-white background, dark
   notation/text, one accent color (used for "now playing" and primary
   buttons). Rounded corners, no visual noise. (Ableton, Soundslice)
2. **The song's timeline is the centerpiece** — waveform on top, drum
   hits/notation below, both synced to one moving playhead. Clicking
   anywhere in either one seeks the audio. (Soundslice, Moises)
3. **Correcting = clicking a grid.** Rows per drum with a distinct color
   each, columns per beat; click to add/remove a hit, and hear the result
   immediately. (Song Maker, Groove Pizza)
4. **Big controls, few of them.** Play/pause, loop a section, slow down.
   Everything else behind a small menu. (Moises, Chordify)
5. **Instant sound on interaction.** Any edit or click gives immediate
   audible/visible feedback — no "apply" buttons.

[ss-hn]: https://www.holovaty.com/writing/soundslice-sheet-music/
[ss-redesign]: https://www.soundslice.com/blog/224/introducing-our-player-redesign/
[moises-rev]: https://liveaspects.com/moises-app-review/
[ableton-blog]: https://sonicbloom.net/two-interactive-websites-by-ableton-learning-music-learning-synths/
[cml-rev]: https://musconv.com/blog/chrome-music-lab-song-maker/
[gp-page]: https://www.musedlab.org/groovepizza/
[songsterr-rev]: https://www.guitarchalk.com/full-songsterr-review/
[chordify-rev]: https://www.guitarchalk.com/chordify-review/
