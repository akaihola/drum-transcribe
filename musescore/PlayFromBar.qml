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
// this file (serverUrl= under [drumtranscribe]). To change it from inside
// MuseScore, run the plugin with nothing selected: a small settings window
// opens. It also opens when the server doesn't answer.

import QtQuick
import QtQuick.Controls
import MuseScore 3.0

MuseScore {
    id: root
    version: "2.1"
    title: "Play/pause from bar"
    description: "Plays the original recording from the selected bar (again to pause) via the drum-transcribe web app"
    categoryCode: "playback"

    // Fallback when drum-transcribe.ini is missing or unreadable.
    property string serverUrl: "http://localhost:8765"
    property var cfg: null

    function loadConfig() {
        // Settings lives in QtCore on new Qt, Qt.labs.settings on old;
        // create it at runtime so a missing module is a caught error, not a
        // plugin that fails to load.
        var ini = Qt.resolvedUrl("drum-transcribe.ini").toString().replace(/^file:\/\//, "");
        var body = 'Settings {\nfileName: "' + ini + '"\n' +
                   'category: "drumtranscribe"\n' +
                   'property string serverUrl: "' + serverUrl + '"\n}';
        try {
            cfg = Qt.createQmlObject("import QtCore\n" + body, root, "cfg");
        } catch (e) {
            try {
                cfg = Qt.createQmlObject("import Qt.labs.settings\n" + body, root, "cfg");
            } catch (e2) {
                console.log("Play/pause from bar: Settings unavailable, using " + serverUrl);
            }
        }
        if (cfg)
            serverUrl = cfg.serverUrl;
    }

    function saveConfig(url) {
        serverUrl = url;
        if (cfg) {
            cfg.serverUrl = url;
            cfg.destroy();  // destruction flushes the ini to disk
            cfg = null;
        }
    }

    function openSettings(message) {
        settingsMessage.text = message;
        urlField.text = serverUrl;
        // show(), not visible = true: for a Window declared inside a
        // never-shown plugin item, Qt defers the visible assignment forever.
        settingsWindow.show();
        settingsWindow.requestActivate();
        urlField.forceActiveFocus();
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
        loadConfig();
        var tick = selectionTick();
        if (tick < 0) {
            openSettings("Nothing is selected. Select a bar to play it — or change the server address below.");
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
                if (xhr.status === 200)
                    quit();
                else
                    openSettings("No answer from " + serverUrl + " — check the address, Save, and try again.");
            }
        };
        xhr.send(JSON.stringify({ "bar": bar }));
    }

    Window {
        id: settingsWindow
        title: "Play/pause from bar — settings"
        width: 480
        height: column.implicitHeight + 24
        flags: Qt.Dialog
        onVisibleChanged: if (!visible) root.quit()

        Column {
            id: column
            anchors.fill: parent
            anchors.margins: 12
            spacing: 8

            Label {
                id: settingsMessage
                width: parent.width
                wrapMode: Text.Wrap
            }
            Label { text: "drum-transcribe server address:" }
            TextField {
                id: urlField
                width: parent.width
                onAccepted: saveButton.clicked()
            }
            Row {
                spacing: 8
                Button {
                    id: saveButton
                    text: "Save"
                    onClicked: {
                        root.saveConfig(urlField.text);
                        settingsWindow.close();
                    }
                }
                Button {
                    text: "Cancel"
                    onClicked: settingsWindow.close()
                }
            }
        }
    }
}
