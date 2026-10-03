"""Trusted state of cloud GPU jobs: one record per version, in its own bucket.

Every rented host holds the results bucket's key, so nothing there can be
trusted. The `drum-transcribe-jobs` bucket admits only the web app's own
key (JOBS_ACCESS_KEY/JOBS_SECRET_KEY) and the owner (its bucket policy).
Records are written with conditional PUTs: of two writers only one wins,
and a write that fails means the caller must act on nothing.

Record ``<song>/<version>.json``:
  job          stable id; inputs live under sources/<job>/ in the results bucket
  url, upload  where the recording came from (upload = bucket key of the original)
  source       bucket key of the published source.<ext>, once prepared
  variants, raw_bars, generation   what to make; markers of other
               generations don't count
  state        open | done | failed
  done         variants whose <variant>/done marker matches the generation
  status       what the page says while waiting (daily cap, checking a rental…)
  attempts     one per rental, from the claim on (coordinator.py)
The container's own log of the version is ``<song>/<version>.log``.
"""

from __future__ import annotations

import functools
import json
import os
import time
import uuid
from pathlib import Path

BUCKET = os.environ.get("JOBS_BUCKET", "drum-transcribe-jobs")


# (song, version) -> the record as last read or written here; pages read
# this, never the bucket
_known: dict[tuple[str, str], dict] = {}


class Conflict(Exception):
    """The record changed since it was read, or already exists."""


def enabled() -> bool:
    """Is this the cloud web app, the one place that rents GPUs?"""
    return bool(os.environ.get("JOBS_ACCESS_KEY") and os.environ.get("VAST_API_KEY"))


@functools.cache
def _s3():
    import boto3  # ty: ignore[unresolved-import]

    return boto3.client(
        "s3", endpoint_url=os.environ.get("S3_ENDPOINT", "https://s3.fr-par.scw.cloud"),
        region_name=os.environ.get("S3_REGION", "fr-par"),
        aws_access_key_id=os.environ["JOBS_ACCESS_KEY"],
        aws_secret_access_key=os.environ["JOBS_SECRET_KEY"])


def new(song: str, version: str, url: str | None = None,
        upload: str | None = None, job: str | None = None) -> dict:
    from .ingest import VARIANTS

    return {"job": job or uuid.uuid4().hex[:12], "song": song, "version": version,
            "url": url, "upload": upload, "source": None, "variants": list(VARIANTS),
            "raw_bars": False, "generation": 1, "state": "open", "done": [],
            "status": "", "created": time.time(), "attempts": []}


def load(song: str, version: str) -> tuple[dict | None, str | None]:
    """(record, etag), or (None, None) if the version has none."""
    from botocore.exceptions import ClientError  # ty: ignore[unresolved-import]

    try:
        r = _s3().get_object(Bucket=BUCKET, Key=f"{song}/{version}.json")
    except ClientError as e:
        if e.response["Error"]["Code"] == "NoSuchKey":
            return None, None
        raise
    return json.loads(r["Body"].read()), r["ETag"]


def save(rec: dict, etag: str | None) -> str:
    """Write ``rec`` only if nobody did since ``etag`` was read (None: only
    if it doesn't exist yet). The new etag, or Conflict."""
    from botocore.exceptions import ClientError  # ty: ignore[unresolved-import]

    cond = {"IfMatch": etag} if etag else {"IfNoneMatch": "*"}
    try:
        r = _s3().put_object(Bucket=BUCKET, Key=f"{rec['song']}/{rec['version']}.json",
                             Body=json.dumps(rec, indent=1).encode(),
                             ContentType="application/json", **cond)
    except ClientError as e:
        if e.response["Error"]["Code"] in ("PreconditionFailed", "412"):
            raise Conflict(f"{rec['song']}/{rec['version']} changed meanwhile") from e
        raise
    _known[rec["song"], rec["version"]] = json.loads(json.dumps(rec))
    return r["ETag"]


_cache: dict[str, tuple[str, bytes]] = {}  # key -> (etag, body): fetch changed ones only


def records() -> list[tuple[dict, str]]:
    """Every record with its etag, each a fresh copy to change and save."""
    s3, found = _s3(), {}
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=BUCKET):
        for obj in page.get("Contents", []):
            if obj["Key"].endswith(".json"):
                found[obj["Key"]] = obj["ETag"]
    for key, etag in found.items():
        if _cache.get(key, ("",))[0] != etag:
            r = s3.get_object(Bucket=BUCKET, Key=key)
            _cache[key] = (r["ETag"], r["Body"].read())
    for key in set(_cache) - set(found):
        del _cache[key]
    recs = [(json.loads(body), etag) for etag, body in _cache.values()]
    global _known
    _known = {(rec["song"], rec["version"]): json.loads(json.dumps(rec)) for rec, _ in recs}
    return recs


def known(song: str, version: str) -> dict | None:
    """The version's record as this process last saw it (None: no cloud job)."""
    return _known.get((song, version))


def remove(song: str, version: str) -> None:
    _known.pop((song, version), None)
    for suffix in (".json", ".log"):
        _s3().delete_object(Bucket=BUCKET, Key=f"{song}/{version}{suffix}")


def push_log(song: str, version: str, path: Path) -> None:
    _s3().upload_file(str(path), BUCKET, f"{song}/{version}.log")


def pull_log(song: str, version: str, path: Path) -> None:
    """Bring back the log a previous container wrote, if there is one."""
    from botocore.exceptions import ClientError  # ty: ignore[unresolved-import]

    try:
        _s3().download_file(BUCKET, f"{song}/{version}.log", str(path))
    except ClientError:
        pass


def unsettled(rec: dict) -> bool:
    """Is a rental of this job still alive, or its creation unresolved?
    Then no new rental, retry, meter change or deletion may start."""
    return any(not a.get("closed") for a in rec["attempts"])


def busy(rec: dict) -> bool:
    return rec["state"] == "open" or unsettled(rec)
