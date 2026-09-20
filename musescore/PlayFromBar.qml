// Play from bar — drum-transcribe companion plugin for MuseScore Studio 4.
//
// Select a note/rest (or a range) and run the plugin (best given a keyboard
// shortcut): the original recording plays from that bar in the drum-transcribe
// web page you have open in your browser. See docs/musescore-plugin.md.
//
// Install: copy this file to ~/Documents/MuseScore4/Plugins, then enable it
// in MuseScore under Home → Plugins and assign a shortcut.

import QtQuick
import MuseScore 3.0

MuseScore {
    version: "1.0"
    title: "Play from bar"
    description: "Plays the original recording from the selected bar via the drum-transcribe web app"
    categoryCode: "playback"

    // Where `drum-transcribe serve` runs; edit if MuseScore is on another machine.
    property string serverUrl: "http://localhost:8765"

    function selectionTick() {
        var sel = curScore ? curScore.selection : null;
        if (!sel)
            return -1;
        if (sel.isRange && sel.startSegment)
            return sel.startSegment.tick;
        for (var i = 0; i < sel.elements.length; i++) {
            var e = sel.elements[i];  // e.g. a note: walk note → chord → segment
            while (e && e.type !== Element.SEGMENT)
                e = e.parent;
            if (e)
                return e.tick;
        }
        return -1;
    }

    onRun: {
        var tick = selectionTick();
        if (tick < 0) {
            console.log("Play from bar: nothing selected");
            quit();
            return;
        }
        var bar = 0;  // 1-based bar number of the measure containing tick
        for (var m = curScore.firstMeasure; m && m.firstSegment.tick <= tick; m = m.nextMeasure)
            bar++;
        var xhr = new XMLHttpRequest();
        xhr.open("POST", serverUrl + "/api/seek");
        xhr.setRequestHeader("Content-Type", "application/json");
        xhr.onreadystatechange = function() {
            if (xhr.readyState === XMLHttpRequest.DONE) {
                if (xhr.status !== 200)
                    console.log("Play from bar: server not reachable at " + serverUrl);
                quit();
            }
        };
        xhr.send(JSON.stringify({ "bar": bar }));
    }
}
