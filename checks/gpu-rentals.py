"""The cloud web app on atom, renting real Vast.ai GPUs, for the checks
mocks can't make (gpu-resilience-handoff.md, "Real-rental checks").

Uses its own buckets and rental label, so it and the cloud web app never
touch each other's jobs or rentals, and starts each time with an empty
output folder, like a new container. Run it from atom's clone, which holds
the keys (.secrets.jobs-s3.json, .secrets.worker-s3.json,
~/.config/vastai/vast_api_key), with the two buckets made first and
deleted after (`, scw object bucket create|delete NAME --profile
drum-transcribe`):

    uv run --with boto3 python checks/gpu-rentals.py PORT [POINT] [--fixed] [--max-hourly=$]

and send it songs as the page does, e.g.
`curl -T song.mp3 'http://127.0.0.1:PORT/api/upload?project=p&version=v&filename=song.mp3&gpu=1'`.

POINT exits at once, like a killed container, at that point of the first
rental: before-create, after-create, before-guard or after-guard.
--fixed rents every try at the fixed price, which can't be outbid while
the image loads (the record still says bid for tries 1-4).
--max-hourly raises the price ceiling when no offer is under it.
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

for arg in sys.argv[2:]:
    if arg.startswith("--max-hourly="):
        patch(coordinator, MAX_HOURLY=float(arg.split("=", 1)[1]))

if "--fixed" in sys.argv:
    offer = coordinator._offer
    patch(coordinator, _offer=lambda fixed, recs: offer(True, recs))

serve.serve(Path(tempfile.mkdtemp(prefix="gpu-rentals-")), "127.0.0.1", int(sys.argv[1]))
