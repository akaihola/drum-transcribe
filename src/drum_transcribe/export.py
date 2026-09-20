"""Convert MusicXML to a MuseScore file (.mscz) with the MuseScore CLI.

Best-effort: MuseScore 4's headless importer aborts (silent exit 40) on
warnings its GUI lets the user ignore, so conversion can fail even for
schema-valid, fully voice-filled scores. MusicXML stays the primary
deliverable; MuseScore opens it directly.

NixOS note: `, mscore` is avoided on purpose — two nixpkgs packages provide
`mscore` (musescore and the musescore-evolution fork) and comma picks
unpredictably, which made conversion results irreproducible.
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
    if shutil.which("nix"):
        candidates.append(["nix", "run", "nixpkgs#musescore", "--"])
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    for cmd in candidates:
        try:
            subprocess.run(
                [*cmd, str(musicxml), "-o", str(mscz)],
                env=env, capture_output=True, timeout=600, check=False,
            )
        except (subprocess.TimeoutExpired, OSError):
            continue
        if mscz.exists():
            return mscz
    return None
