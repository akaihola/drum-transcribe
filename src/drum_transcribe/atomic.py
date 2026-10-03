"""Crash-safe file writes: a reader never sees a half-written file."""

import os
from pathlib import Path


def write_text(path: Path, text: str) -> None:
    """Write to a temp file, then rename it over ``path``.

    A crash leaves either the old file or none, never a truncated one that
    a later run would take for a finished result.
    """
    tmp = path.with_name(f".{path.name}.part")
    tmp.write_text(text)
    os.replace(tmp, path)
