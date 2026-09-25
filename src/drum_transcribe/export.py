"""Convert MusicXML to a MuseScore file (.mscz) with the MuseScore CLI.

The command comes from the MUSESCORE_CMD env var (default: `musescore`);
on this NixOS laptop it is set to `, musescore` (comma) until MuseScore
is installed properly. Never use `, mscore` — two nixpkgs packages
provide `mscore` and comma picks unpredictably.

MuseScore 4's CLI refuses scores that fail its corruption check (silent
exit 40; the reason is only in MuseScore's own log file, see
docs/notation-musescore.md). Then the reasons are saved next to the
.mscz as PROBLEMS and the conversion is redone with `-f`, which saves the
score anyway so the user has something to fix in MuseScore.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import time
from pathlib import Path

PROBLEMS = "mscz-problems.txt"


def _convert(cmd: list[str], musicxml: Path, mscz: Path, *flags: str) -> bool:
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    try:
        subprocess.run(
            [*cmd, *flags, str(musicxml), "-o", str(mscz)],
            env=env, capture_output=True, timeout=600, check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    return mscz.exists()


def _logged_errors(since: float) -> list[str]:
    """Load errors MuseScore wrote to its log files since `since`."""
    data = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
    errors = []
    for log in (data / "MuseScore/MuseScore4/logs").glob("*.log"):
        if log.stat().st_mtime < since:
            continue
        for line in log.read_text(errors="replace").splitlines():
            # "... failed load notation, err: [2009] <b>Incomplete measure</b>: ..., path: ..."
            if "failed load notation, err: " in line:
                msg = line.split("err: ", 1)[1].rsplit(", path: ", 1)[0]
                errors.append(re.sub(r"<[^>]+>|^\[\d+\] ", "", msg))
    return errors


def to_mscz(musicxml: Path, mscz: Path) -> Path | None:
    """Convert; on refusal record the reasons in PROBLEMS and force it."""
    cmd = shlex.split(os.environ.get("MUSESCORE_CMD", "musescore"))
    problems = mscz.parent / PROBLEMS
    mscz.unlink(missing_ok=True)
    problems.unlink(missing_ok=True)
    start = time.time() - 1  # log mtimes can have 1 s resolution
    if _convert(cmd, musicxml, mscz):
        return mscz
    errors = _logged_errors(start) or ["MuseScore refused the file (no reason logged)."]
    problems.write_text("\n".join(errors) + "\n")
    return mscz if _convert(cmd, musicxml, mscz, "-f") else None
