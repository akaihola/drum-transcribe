"""Convert MusicXML to a MuseScore file (.mscz) with the MuseScore CLI.

The command comes from the MUSESCORE_CMD env var (default: `musescore`);
on this NixOS laptop it is set to `, musescore` (comma) until MuseScore
is installed properly. Never use `, mscore` — two nixpkgs packages
provide `mscore` and comma picks unpredictably.

Best-effort: MuseScore 4's CLI refuses scores that fail its corruption
check (silent exit 40; the reason is in MuseScore's own log file, see
docs/notation-musescore.md). MusicXML stays the primary deliverable;
MuseScore opens it directly.
"""

from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path


def to_mscz(musicxml: Path, mscz: Path) -> Path | None:
    cmd = shlex.split(os.environ.get("MUSESCORE_CMD", "musescore"))
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    try:
        subprocess.run(
            [*cmd, str(musicxml), "-o", str(mscz)],
            env=env, capture_output=True, timeout=600, check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    return mscz if mscz.exists() else None
