// Pause playback — drum-transcribe companion plugin for MuseScore Studio 4.
//
// Pauses the recording that the "Play from bar" plugin started in the
// drum-transcribe web page. Install and enable like PlayFromBar.qml
// (see that file), and assign it a keyboard shortcut.

import QtQuick
import MuseScore 3.0

MuseScore {
    version: "1.0"
    title: "Pause recording"
    description: "Pauses the recording playing in the drum-transcribe web app"
    categoryCode: "playback"

    // Where `drum-transcribe serve` runs; edit if MuseScore is on another machine.
    property string serverUrl: "http://localhost:8765"

    onRun: {
        var xhr = new XMLHttpRequest();
        xhr.open("POST", serverUrl + "/api/seek");
        xhr.setRequestHeader("Content-Type", "application/json");
        xhr.onreadystatechange = function() {
            if (xhr.readyState === XMLHttpRequest.DONE) {
                if (xhr.status !== 200)
                    console.log("Pause recording: server not reachable at " + serverUrl);
                quit();
            }
        };
        xhr.send(JSON.stringify({ "bar": 0 }));  // bar 0 = pause
    }
}
