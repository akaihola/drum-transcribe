# Style guide

The visual style for the web app, distilled from [design-inspiration.md]
(design-inspiration.md). The living version is [style-guide.html]
(style-guide.html) — open **`/style`** on the running server to see every
color, font and control rendered for real.

## The idea: ink on a drumhead

The page looks like drum notation does: warm black ink on the off-white of a
coated drumhead. One accent color — a teal named after the "sea-blue
sparkle" drum-shell finish — is reserved for a single meaning: **sound
happens here**. The bar being played, the active version tab, the button
that starts playback. If something is teal, clicking it makes music; nothing
teal is decoration.

Two colors already had meanings in the app and keep them: brass amber for
work in progress and saved feedback, signal red for low-confidence
transcribed hits and errors.

## Tokens

| name | value | used for |
|---|---|---|
| drumhead white | `#FAF9F6` | page background |
| notation ink | `#232019` | text, scores, active tab |
| quiet ink | `#6E675C` | captions, stats |
| sea-blue sparkle | `#0E7386` | playhead, active elements, primary button |
| teal (deep) | `#0A5766` | links, hover |
| teal wash | `rgba(14,115,134,.15)` | the bar playing right now |
| brass | `#A66300` | in-progress, saved feedback |
| signal red | `#C40000` | transcribed hits, errors |
| hairline | `#E2DDD2` | borders |

Fonts (Google Fonts CDN, like Verovio already is): **Alegreya** serif for
song titles and headings — it echoes an engraved score's title page —
and **Alegreya Sans** for everything else. Body 17px, line-height 1.55,
text columns under 65 characters.

Shapes: pill-round buttons and tabs (`999px`), gently rounded boxes (`8px`).
No cards, no gradients; the only shadows are under floating menus and
dialogs.

## Layout

The score is the central element of a project page: notation gets the full
width and most of the height. Playback controls are compact and always easy
to reach while reading the score. Text (help, forms, captions) stays in a
column under 65 characters; scores are never squeezed into one.

## Rules of thumb

- One teal button per screen — the main action. Secondary actions are quiet
  outlines. Buttons say what they do ("Transcribe", not "Submit").
- Players sit on white "sound cards": a teal left edge (teal = this plays),
  a one-line caption saying what you are hearing, and the browser's own
  controls recolored to blend in (Chromium; other browsers just show their
  native controls on the card).
- Errors say what went wrong and what to try.
- Visible keyboard focus (teal outline); animations respect the browser's
  reduced-motion setting.
