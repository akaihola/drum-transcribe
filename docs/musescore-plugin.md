# Play-from-bar inside MuseScore

Goal: while refining a score in MuseScore Studio, select a bar and press a
shortcut → the original recording plays from that bar. **Built 2026-09-20**:
[musescore/PlayFromBar.qml](../musescore/PlayFromBar.qml), installed on this
laptop at `~/Asiakirjat/MuseScore4/Plugins/` (the XDG Documents dir is
Finnish here). Enable under Home → Plugins and assign a shortcut. One plugin
does both play and pause (MuseScore allows one shortcut per plugin, so the
web page toggles: a repeated bar while audio plays means pause). The server
address is read from `drum-transcribe.ini` next to the plugin via a
runtime-created `Settings` (QtCore, falling back to `Qt.labs.settings` —
`Qt.createQmlObject` so a missing module can't break plugin load; pattern
from hoshi005's AudioSync; on 4.7 QtCore Settings is unavailable and the
fallback is what actually runs). **Settings window added 2026-09-20** ("Option
2"): running the plugin with nothing selected, or when the server doesn't
answer, opens a small window to edit and Save the server address into the
same ini; the shortcut fast path stays window-free. Verified end-to-end in
the headless GUI (see below): all four paths — no selection, Save→ini,
selection→POST, dead server→warning.
Server side: `POST /api/seek {bar}` bumps a `{seq, bar}` counter;
project pages poll `GET /api/seek` every 1 s and seek the active version
tab's audio (polling chosen over SSE — zero connection management).

## Target environment

- MuseScore Studio **4.7.4.1** on NixOS (user's machine). The plugin API is
  Qt 6 based from 4.4 (`import MuseScore`, unversioned `QtQuick` imports)
  and was fully restored in 4.6, so 4.7 has everything needed.
- Plugins are installed by dropping the `.qml` file in the MuseScore
  plugins folder (on Linux by default `~/Documents/MuseScore4/Plugins` —
  verify on the NixOS machine), then enabled and given a keyboard shortcut
  under Home → Plugins → manage.

## Architecture

```
MuseScore QML plugin ──HTTP POST /api/seek {bar}──▶ drum-transcribe server
                                                          │ push event
                                                          ▼
                              open project page seeks its audio to the bar
                              (existing barTimes + click-to-play seek code)
```

- The plugin sends **only the bar number**. The server/page own the
  bar→seconds map (`beats.json`), so tempo drift in the recording is
  handled correctly and the plugin needs no per-project configuration.
- The page applies the event to the **currently active version tab** and
  picks the player with the existing rules (playing > last used > original).
  So the plugin doesn't need to know project or version at all — whatever
  page (and tab) the user has open is the target. Single-user assumption,
  fine here.
- Audio plays in the browser, on whichever machine has the page open —
  consistent with the project's web-first rule. The browser allows
  script-triggered playback once the user has interacted with the page
  (one manual play click per page load is enough).

## Plugin sketch (QML, ~50 lines)

- No-UI, run-and-quit style: `onRun` reads the selection, POSTs, `quit()`.
  Triggered via its keyboard shortcut. (A tiny persistent dialog with a
  Play button is the fallback if run-and-quit feels clunky.)
- Read the selected bar: `curScore.selection.elements[0]`; get its tick
  (walk note → chord → segment, or for range selections
  `curScore.selection.startSegment.tick`); then count measures from
  `curScore.firstMeasure` via `.nextMeasure` until the one containing the
  tick → 1-based bar number. (A `Cursor` with `rewind(Cursor.SELECTION_START)`
  works for range selections only; the element walk covers single clicks.)
- POST via QML `XMLHttpRequest` (confirmed working in MS4 plugins) to
  `http://<server>:8765/api/seek` with body `{"bar": N}`. Server URL as a
  `property string` constant at the top of the file, edited once by hand.
- Do **not** also start MuseScore's own playback (`cmd("play")` works, but
  synthesized drums on top of the recording defeats the purpose).

## Server + page changes

- `POST /api/seek {bar}` → remember `{seq, bar}` and wake waiters.
- Push to the page, stdlib only (pick at build time):
  - **SSE** (`GET /api/events`, `text/event-stream`): instant, one held
    thread per open page in `ThreadingHTTPServer`, `threading.Condition`
    to broadcast; or
  - **polling** (page fetches `{seq, bar}` every ~1 s and acts when `seq`
    changes): dumbest thing that works, zero connection management.
- Page: factor the click-to-play handler's seek block into
  `seekToBar(section, bar)` and call it for both the click and the event.

## Facts from the 2026-09-20 research (don't re-research)

Confirmed working in MS4 plugins: reading selection and ticks, tick→seconds
via the score's tempo map (`cursor.time`; a method with repeats support in
4.6+), plugin keyboard shortcuts, `XMLHttpRequest`, `cmd("play")` (playback
starts from the current selection). API reference: repo headers
`src/engraving/api/v1/` (authoritative), the 3.x docs at
<https://musescore.github.io/MuseScore_PluginAPI_Docs/plugins/html/> (still
mostly applicable), community hub "Plugins for 4.x"
<https://musescore.org/en/node/337468>. In-app Plugin Creator
(Ctrl+Shift+P) for live testing.

Facts from building the settings window (2026-09-20):

- A `Window {}` declared inside the plugin item **never shows via
  `visible = true`** — Qt defers the assignment because the plugin item
  itself is never shown. Call `settingsWindow.show()` instead; that maps it
  immediately (verified: `visible` stays `false` after assignment, `true`
  after `show()`).
- Plugin QML is **cached for the whole MuseScore session** — after editing
  the .qml you must restart MuseScore (or use the Plugin Creator), or the
  old code keeps running.
- `console.log` from plugins appears in neither stdout nor MuseScore's log
  files. To debug, POST debug strings via `XMLHttpRequest` to a local stub
  server and read its log.

Dead ends — confirmed broken/removed in MS4, do not retry:

- Plugins **cannot play audio** (QtMultimedia not shipped in the plugin QML
  environment) — hence the external-player architecture.
- No dock panels; `onScoreStateChanged` never fires
  ([#20290](https://github.com/musescore/MuseScore/issues/20290) open) →
  cannot auto-react to selection changes, cannot draw play buttons on the
  score canvas. Select + shortcut is the best available UX.
- No API for live playback position; MS3's OSC remote (port 5282) and JACK
  transport were both dropped in MS4 → "recording follows spacebar" is
  impossible.
- QtWebSockets broke in 4.4
  ([#24360](https://github.com/musescore/MuseScore/issues/24360)) → use
  plain XHR, not WebSocket, on the plugin side.
- `newQProcess()` is limited/buggy
  ([#20920](https://github.com/musescore/MuseScore/issues/20920)) — not
  needed in this design anyway.

Prior art (reference implementations):

- [hoshi005/musescore-audio-sync](https://github.com/hoshi005/musescore-audio-sync)
  (GPL-3, MS 4.6+): the same idea — measure click → HTTP to a localhost
  helper that plays the recording. Steal its selection/tick QML code; its
  helper is macOS-only and it trusts the score's tempo map (we use
  `beats.json` instead, which is strictly better).
- [Xeena2812/musescore-audio-companion](https://github.com/Xeena2812/musescore-audio-companion)
  (MS 4.6.5, Linux): plugin → headless VLC over HTTP; proves the pattern on
  Linux.
- [hjamet/AudioScoreTranscriber](https://github.com/hjamet/AudioScoreTranscriber):
  MS4 QML ↔ Python sidecar precedent.
- MuseScore's own roadmap lists "audio staves" (recording synced into the
  score, time-stretched to the tempo map) for ~5.0 — the eventual native
  replacement for this plugin.

## Known caveats

- **Bar numbering must match `beats.json`'s bar counter** (downbeat count,
  first downbeat = bar 1). Generated scores have no pickup bar today. If
  the user *inserts or deletes measures* while refining, numbering shifts
  and the sync goes stale from that point on — accepted limitation; the
  authoritative fix is regenerating the score.
- Repeats: the transcription is linear (no repeat barlines generated), so
  tick↔bar is unambiguous. If repeats are ever added by hand, measure
  counting still works (we count physical measures, not playback order).
- Server must be reachable from the MuseScore machine (port 8765 firewall
  note in [operations.md](operations.md)).

## Testing the plugin in a headless GUI (verified 2026-09-20)

An agent can run the full MuseScore GUI on a private virtual display,
see it via screenshots, and drive it with synthetic mouse/keyboard —
end-to-end verified: selecting measure 3 and triggering the plugin from
the Lisäosat → Toisto menu bumped the server's `/api/seek` to
`{"bar": 3}`.

```bash
Xvfb :99 -screen 0 1600x1000x24 &          # private headless X server

# Isolated profile: HOME alone is NOT enough — the login session exports
# XDG_CONFIG_HOME etc. pointing at the real home, and Qt prefers those.
# XDG_RUNTIME_DIR must also be private, or MuseScore's multi-instance
# IPC routes "open this score" to the user's running instance.
M=/tmp/claude/mshome
mkdir -p $M/.config $M/.local/share $M/.cache $M/.local/state
mkdir -p -m 700 $M/runtime
cp -r ~/.config/MuseScore $M/.config/          # keeps plugin enabled
cp -r ~/.local/share/MuseScore $M/.local/share/
mkdir -p $M/Asiakirjat/MuseScore4/Plugins      # user-dirs name Asiakirjat
cp ~/Asiakirjat/MuseScore4/Plugins/{PlayFromBar.qml,drum-transcribe.ini} \
   $M/Asiakirjat/MuseScore4/Plugins/

env -u WAYLAND_DISPLAY HOME=$M XDG_CONFIG_HOME=$M/.config \
  XDG_DATA_HOME=$M/.local/share XDG_CACHE_HOME=$M/.cache \
  XDG_STATE_HOME=$M/.local/state XDG_RUNTIME_DIR=$M/runtime \
  DISPLAY=:99 QT_QPA_PLATFORM=xcb \
  "$(dirname "$(readlink -f "$(command -v mscore || echo /nix/store/*musescore*/bin/mscore)")")"/mscore \
  /path/to/copy-of-score.mscz &                # open a COPY: the real
                                               # path may be open in the
                                               # user's instance → IPC
                                               # routes it there
DISPLAY=:99 import -window root shot.png       # observe (ImageMagick)
nix-shell -p xdotool                           # interact
```

Interaction notes: pixel-clicking noteheads is fragile; keyboard is
deterministic — `xdotool key ctrl+Home` selects the first element,
`ctrl+Right` advances one measure, and the status bar shows
"…Tahti: N; Isku: M". Trigger the plugin from Lisäosat → Toisto (menu
click) and confirm with `curl localhost:8765/api/seek`. Close with
`xdotool key ctrl+q` (exits 0), then kill Xvfb. Caveat: a test trigger
bumps the live server's seek counter, so any open project page will
seek/toggle once. To avoid that, point the test ini at a local stub
server that answers 200 to POST and logs bodies.

More gotchas learned 2026-09-20:

- **The isolated instance reads plugins from `$M/Documents/MuseScore4/
  Plugins`, not `$M/Asiakirjat/…`** — user-dirs.dirs is not copied, so Qt
  falls back to the English Documents dir. Install the plugin (and its
  ini) there, or copy `~/.config/user-dirs.dirs` too.
- The plugin menu item is **disabled while no score is open** (Home tab).
- Dismiss the update dialog and the "restore session?" dialog by
  coordinates from a screenshot; the recents list points at real-home
  files, so open only the score passed on the command line (a copy).
- QML submenus don't open reliably from a fast click; click the top-level
  menu, then *hover* the submenu entry ~2 s, screenshot to confirm it
  expanded, then click the item.

## Alternative kept in the back pocket ("Route 3")

Write the measured per-bar tempo map into the exported MusicXML as (hidden)
tempo changes. Then MuseScore's own playback timeline matches the recording,
and unmodified third-party tools (Audio Sync plugin, musescore.com's
score↔YouTube sync) line up too. Costs: tempo-mark clutter in the score and
extra load on the already-fragile .mscz conversion. Only worth trying if the
plugin route disappoints.
