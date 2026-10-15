"""The cloud web app on atom, renting real Vast.ai GPUs, for the checks
mocks can't make (docs/tasks/8-cloud-gpu-checks-on-real-rentals.md).

Uses its own buckets and rental label, so it and the cloud web app never
touch each other's jobs or rentals, and starts each time with an empty
output folder, like a new container. Run it from atom's clone, which holds
the keys (.secrets.jobs-s3.json, .secrets.worker-s3.json,
~/.config/vastai/vast_api_key):

    uv run --with boto3 python checks/gpu-rentals.py PORT [POINT] [--park]

POINT exits at once, like a killed container, at that point of the first
rental: before-create, after-create, before-guard or after-guard.
--park bids tries 1-4 at half the going rate without cancel_unavail, so
Vast parks each as stopped; the fifth rents at the fixed price.
"""

import functools
import json
import os
import sys
import tempfile
from pathlib import Path

JOBS, RESULTS = "drum-transcribe-check-jobs", "drum-transcribe-check-results"
keys = json.loads(Path(".secrets.jobs-s3.json").read_text())
os.environ.update(JOBS_BUCKET=JOBS, JOBS_ACCESS_KEY=keys["access_key"],
                  JOBS_SECRET_KEY=keys["secret_key"],
                  VAST_API_KEY=(Path.home() / ".config/vastai/vast_api_key").read_text().strip())

from drum_transcribe import coordinator, gate, serve, vast

worker = json.loads(Path(".secrets.worker-s3.json").read_text())


@functools.cache
def results_bucket():
    import boto3  # ty: ignore[unresolved-import]

    return boto3.client("s3", endpoint_url=worker["endpoint"], region_name=worker["region"],
                        aws_access_key_id=worker["access_key"],
                        aws_secret_access_key=worker["secret_key"]), RESULTS


def die(point: str, *_) -> None:
    print(f"gpu-rentals: exiting {point}", flush=True)
    os._exit(1)


def patch(module, **attrs):
    """Swap attributes; the code under test calls them through the module."""
    for name, value in attrs.items():
        setattr(module, name, value)


patch(gate, results_bucket=results_bucket)
patch(coordinator, LABEL="drum-transcribe-check/")  # the cloud web app sweeps only its own
create, add_guard = vast.create, vast.add_guard
point = next((a for a in sys.argv[2:] if not a.startswith("--")), "")
patch(vast, **{
    "": {},
    "before-create": {"create": functools.partial(die, point)},
    "after-create": {"create": lambda *a: die(f"{point}: instance {create(*a)}")},
    "before-guard": {"add_guard": functools.partial(die, point)},
    "after-guard": {"add_guard": lambda *a: die(f"{point}: guard {add_guard(*a)}")},
}[point])

if "--park" in sys.argv:
    payload = coordinator._Job.payload

    def parked(self, a, offer):
        p = payload(self, a, offer)
        if a["type"] == "bid":
            p.update(price=round(offer["min_bid"] / 2, 4), cancel_unavail=False)
        return p

    patch(coordinator._Job, payload=parked)

serve.serve(Path(tempfile.mkdtemp(prefix="gpu-rentals-")), "127.0.0.1", int(sys.argv[1]))
