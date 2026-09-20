// Play/pause from bar — drum-transcribe companion plugin for MuseScore Studio 4.
//
// Select a note/rest (or a range) and run the plugin (best given a keyboard
// shortcut): the original recording plays from that bar in the drum-transcribe
// web page you have open in your browser. Run it again with the same bar
// selected to pause; select another bar to jump there while playing.
// See docs/musescore-plugin.md.
//
// Install: copy this file to the MuseScore4/Plugins folder under your
// Documents, then enable it in MuseScore under Home → Plugins and assign a
// shortcut. The server address is read from drum-transcribe.ini next to
// this file (serverUrl= under [drumtranscribe]).

import QtQuick
import MuseScore 3.0

MuseScore {
    id: root
    version: "2.0"
    title: "Play/pause from bar"
    description: "Plays the original recording from the selected bar (again to pause) via the drum-transcribe web app"
    categoryCode: "playback"

    // Fallback when drum-transcribe.ini is missing or unreadable.
    property string serverUrl: "http://localhost:8765"

    function loadConfig() {
        // Settings lives in QtCore on new Qt, Qt.labs.settings on old;
        // create it at runtime so a missing module is a caught error, not a
        // plugin that fails to load.
        var ini = Qt.resolvedUrl("drum-transcribe.ini").toString().replace(/^file:\/\//, "");
        var body = 'Settings {\nfileName: "' + ini + '"\n' +
                   'category: "drumtranscribe"\n' +
                   'property string serverUrl: "' + serverUrl + '"\n}';
        try {
            serverUrl = Qt.createQmlObject("import QtCore\n" + body, root, "cfg").serverUrl;
        } catch (e) {
            try {
                serverUrl = Qt.createQmlObject("import Qt.labs.settings\n" + body, root, "cfg").serverUrl;
            } catch (e2) {
                console.log("Play/pause from bar: Settings unavailable, using " + serverUrl);
            }
        }
    }

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
            console.log("Play/pause from bar: nothing selected");
            quit();
            return;
        }
        loadConfig();
        var bar = 0;  // 1-based bar number of the measure containing tick
        for (var m = curScore.firstMeasure; m && m.firstSegment.tick <= tick; m = m.nextMeasure)
            bar++;
        var xhr = new XMLHttpRequest();
        xhr.open("POST", serverUrl + "/api/seek");
        xhr.setRequestHeader("Content-Type", "application/json");
        xhr.onreadystatechange = function() {
            if (xhr.readyState === XMLHttpRequest.DONE) {
                if (xhr.status !== 200)
                    console.log("Play/pause from bar: server not reachable at " + serverUrl);
                quit();
            }
        };
        xhr.send(JSON.stringify({ "bar": bar }));
    }
}
