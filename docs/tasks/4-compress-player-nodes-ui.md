# Compress player nodes UI

Now that waveforms are shown in the separate player and not in the player nodes,
we could use UI space more economically in the nodes. Make three proposals for
how the arrow-connected nodes could take less space but still remain equally
usable both on desktop and on portrait mobile.

## Plan, 2026-10-03

Provide three interactive proposals at `/player-layouts` on the existing web
server. Keep the six tracks and their real connections visible or reachable,
with one shared player and a details area for explanations and downloads.
Use recordings already on the server so selecting tracks and opening files can
be tried. The project pages keep their current layout while these are compared.

1. **Compact tree.** Keep the familiar four rows. Make the whole node a large
   selection button; move help, counts and downloads to the shared details area.
2. **Sideways flow.** Use four columns on desktop. On phones, use full-width rows
   with arrows in the left margin. Keep all six tracks directly selectable.
3. **Fold-away sources.** Keep the three transcription tracks visible. Put the
   original, drums and without-drums tracks behind one disclosure. Retain arrows
   from its drums-stem summary to the transcription tracks while folded.

Use the existing paper, ink and teal colors. Keep touch controls at least 44 px
high, keyboard focus visible and selection named in text. Include a portrait
preview on desktop and let the page fit a real phone without horizontal scrolling.
Show sample processing and failed states separately from real recording status.

Verify all proposals with PinchTab, including narrow screens, selection,
disclosure, help, downloads and sample progress. Review the code and run the
cached pipeline smoke check before merging. Record findings here and mark the
proposal task complete awaiting user acceptance. Implementing a chosen design
is a later task.
