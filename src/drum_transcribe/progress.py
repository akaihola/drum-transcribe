"""Live progress of a version's processing job, estimated from pipeline.log.

Stage markers in the log (``== what == 2026-09-22T09:03:41Z``, see
``ingest.marker``) say which step is running and since when. How long a
step should take comes from timings measured on atom's CPU and on a rented
RTX 3090, scaled by the song's length. A step that reports real progress
(yt-dlp's download percentage, Demucs' progress bar) replaces the
time-based guess. Past its expected time a step creeps towards, but never
reaches, its end.
"""

from __future__ import annotations

import math
import re
import subprocess
import time
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from .ingest import VARIANTS

# Per task, its steps in order: (marker prefix, what the page says,
# expected seconds on the CPU as (fixed, per second of song), the same on
# the GPU or None if no different). "pull" is worked out from the rented
# host's download speed.
_START = [("running pipeline", "Starting up", (1, 0), None),
          ("separating drums stem", "Loading the drums stem", (1, 0), None)]
# on the GPU "writing outputs" also covers the upload of the variant's
# files to the bucket (2 min for a 4.5 min song; adtof's, carrying the
# recording and drums stem too, 4 min)
_END = [("quantizing", "Fitting the hits onto the beat grid", (1, 0), None),
        ("writing outputs", "Writing the score and the sonification",
         (1, .01), (30, .4))]
_ADTOF = ("detecting drum hits", "ADTOF is reading the drum hits",
          (1, .04), (5, .06))
_SPLIT = ("splitting kit", "Splitting the drums into six per-drum tracks",
          (5, 6.5), (8, .1))
STEPS = {
    "src": [("downloading", "Downloading the recording", (10, 0), None),
            ("extracting audio", "Extracting the audio track", (3, .01), None)],
    "gpu": [("uploading source", "Handing the recording to the cloud",
             (5, .03), None),
            ("processing on a rented", "Starting the rental", (3, 0), None),
            ("searching spot offers", "Looking for a free cloud GPU", (5, 0), None),
            ("launching instance", "Renting the machine", (8, 0), None),
            ("waiting for ssh",
             "Loading the transcription software onto the machine", "pull", None),
            ("checking the GPU", "Checking that the GPU works", (10, 0), None),
            ("running ", "Fetching the recording onto the machine", (8, 0), None)],
    "drums": [("running pipeline", "Starting up", (1, 0), None),
              ("separating drums stem",
               "Demucs is isolating the drums from the rest of the band",
               (2, .34), (8, .045))],
    "adtof": [*_START,
              ("tracking beats", "Finding the beats and barlines", (1, .03), (10, .05)),
              _ADTOF, *_END],
    "mdx23c": [*_START, _SPLIT,
               ("detecting per-stem onsets", "Finding the hits in each per-drum track",
                (1, .01), (2, .035)), *_END],
    # fused runs after mdx23c, so the six tracks are already there
    "fused": [*_START, ("splitting kit", "Loading the six per-drum tracks", (1, 0), None),
              _ADTOF,
              ("refining with per-drum stems",
               "Checking the hits against the per-drum tracks", (1, .01), (1, .02)),
              *_END],
}
NAMES = {"src": "the recording", "gpu": "the cloud GPU",
         "drums": "the drums stem", **{v: v for v in VARIANTS}}

MARKER = re.compile(r"== (.+?) ==(?: (\S+Z))?\s*$")
JOB_END = re.compile(r"^(== all pipelines finished ==|ERROR:).*$", re.MULTILINE)
# yt-dlp's "[download]  45.3% of 5.2MiB" and tqdm's " 45%|████"
PERCENT = re.compile(r"(\d{1,3}(?:\.\d+)?)%(?:\||\s+of)")
IMAGE_BITS = 8e9 * 8  # the GPU image, compressed


def version_progress(vdir: Path, running: bool) -> dict:
    """{"job": running|failed|stopped|None, "tasks": {task: {...}}, "sig"}.

    A task is listed only while its result is missing, with a state
    (queued, running, arriving, failed, stopped), a percentage, seconds
    until it is ready (None when that can't be told) and what it is doing.
    """
    ready = {"src": any(vdir.glob("source.*")),
             "drums": any(vdir.glob("stems/htdemucs/*/drums.wav")),
             **{v: (vdir / v / "sonification.wav").exists() for v in VARIANTS}}
    log = vdir / "pipeline.log"
    text = log.read_text(errors="replace") if log.exists() else ""
    ends = list(JOB_END.finditer(text))
    current = text[ends[-1].end():] if ends else text
    if running:
        job, tasks = "running", _running(vdir, current, ready)
    elif current.strip():
        job = "stopped"  # log unfinished, but no job thread: server restarted
    elif ends and ends[-1][1] == "ERROR:":
        job = "failed"
    else:
        job, tasks = None, {}
    if job in ("stopped", "failed"):
        tasks = {t: {"state": job, "pct": 0, "eta": None, "activity": ""}
                 for t in ready if not ready[t]}
    # changes whenever the page has something new to show
    results = [*vdir.glob("source.*"), *vdir.glob("stems/htdemucs/*/drums.wav"),
               *vdir.glob("*/sonification.wav"), *vdir.glob("*/score.musicxml"),
               vdir / "beats.json", vdir / "keep-raw-bars"]
    sig = " ".join([str(job), *(f"{f.relative_to(vdir)}@{f.stat().st_mtime_ns}"
                                for f in results if f.exists())])
    return {"job": job, "tasks": tasks, "sig": sig}


def _running(vdir: Path, log: str, ready: dict) -> dict:
    lines = log.splitlines()
    marks = []  # (task, step index, start time, line number)
    variant = first = None
    for n, line in enumerate(lines):
        if not (m := MARKER.match(line)):
            continue
        what, ts = m[1], m[2]
        if what.startswith("running pipeline:"):
            variant = what.split(":", 1)[1].strip()
            first = first or variant
        tasks = (("src", "gpu") if variant is None else
                 ("drums", variant) if variant == first else (variant,))
        for task in tasks:
            k = next((k for k, s in enumerate(STEPS.get(task, []))
                      if what.startswith(s[0])), None)
            if k is not None:
                t = datetime.fromisoformat(ts).timestamp() if ts else time.time()
                marks.append((task, k, t, n))
                break
    gpu = any(m[0] == "gpu" for m in marks)
    syncing = "== syncing results" in log
    order = [t for t in STEPS if t != "gpu" or gpu]
    task_now, k_now, started, n_now = marks[-1] if marks else ("src", 0, time.time(), 0)
    # results downloading from the bucket: every task is done on the GPU
    i_now = len(order) if syncing else order.index(task_now)
    tail = "\n".join(lines[n_now:])  # log since the current step started
    tries = sum(1 for m in marks if m[:2] == ("gpu", 2))
    seconds = _song_seconds(vdir)

    out, before = {}, 0.0  # seconds until all tasks so far are done, or None
    for i, task in enumerate(order):
        expected = [_expect(s, seconds, gpu, log) for s in STEPS[task]]
        if i < i_now:  # done, says the log
            if task != "gpu" and not ready[task]:  # made on the GPU, not here yet
                out[task] = {"state": "arriving", "pct": 100, "eta": None,
                             "activity": "Downloading the results from the cloud"
                             if syncing else "Done on the cloud GPU — the files "
                             "arrive when all pipelines are finished"}
            continue
        if i > i_now:
            pct, left, activity = 0, sum(expected), f"Starts after {NAMES[order[i - 1]]}"
        else:
            pct, left, activity = _step(STEPS[task], k_now, started, expected, tail)
            if task == "gpu" and tries > 1:
                activity += f" (the first machine failed; try {tries} of 3)"
        before = None if before is None or left is None else before + left
        if task != "gpu" and ready[task]:
            continue  # a re-run: the old result stays playable meanwhile
        out[task] = {"state": "running" if i == i_now else "queued", "pct": pct,
                     "eta": None if before is None else round(before),
                     "activity": activity}
    return out


def _step(steps: list, k: int, started: float, expected: list,
          tail: str) -> tuple[int, float | None, str]:
    """(percent of the task, seconds left or None if overdue, activity)."""
    elapsed, e = max(0.0, time.time() - started), expected[k]
    activity = steps[k][1]
    if found := PERCENT.findall(tail):  # the step reports its own progress
        frac = min(float(found[-1]) / 100, 1)
        left = elapsed / frac * (1 - frac) if frac > .02 else e
    else:
        u = elapsed / e
        frac = u if u <= .9 else .9 + .09 * (1 - math.exp((.9 - u) / .5))
        left = e - elapsed if u < 1.1 else None
    if steps[k][2] == "pull" and "instance running" in tail:
        frac, left = max(frac, .95), 15.0  # container is up, ssh any second
    if left is None:
        activity += " — taking longer than usual"
    else:
        left += sum(expected[k + 1:])
    pct = round(100 * (sum(expected[:k]) + e * frac) / sum(expected))
    return pct, left, activity


def _expect(step: tuple, seconds: float, gpu: bool, log: str) -> float:
    """Expected duration of one step in seconds."""
    if step[2] == "pull":
        down = re.findall(r"(\d+) Mbit/s", log)
        return 45 + IMAGE_BITS / (float(down[-1]) * 1e6) * 6 if down else 480
    fixed, per = step[3] if gpu and step[3] else step[2]
    return max(1.0, fixed + per * seconds)


def _song_seconds(vdir: Path) -> float:
    source = next(vdir.glob("source.*"), None)
    return _duration(source, source.stat().st_mtime) if source else 240.0


@lru_cache(maxsize=256)
def _duration(path: Path, _mtime: float) -> float:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, timeout=10, check=False).stdout
        return float(out)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return 240.0
