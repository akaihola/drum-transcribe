"""Convert MusicXML to a MuseScore file (.mscz) with the MuseScore CLI.

Looks for `mscore`/`musescore` on PATH and falls back to NixOS `comma`
(`, mscore`), which fetches the program on demand. Best-effort: returns None
if no converter is available.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


def to_mscz(musicxml: Path, mscz: Path) -> Path | None:
    candidates: list[list[str]] = []
    for exe in ("mscore", "musescore", "mscore4portable"):
        if shutil.which(exe):
            candidates.append([exe])
    if shutil.which(","):
        candidates += [[",", "mscore"], [",", "musescore"]]
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    for cmd in candidates:
        try:
            result = subprocess.run(
                [*cmd, "-o", str(mscz), str(musicxml)],
                env=env, capture_output=True, timeout=600, check=False,
            )
        except (subprocess.TimeoutExpired, OSError):
            continue
        if result.returncode == 0 and mscz.exists():
            return mscz
    return None
