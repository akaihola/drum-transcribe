"""The Vast.ai REST calls the coordinator needs, with errors that tell
whether a request may have taken effect.

Talks to the API directly rather than through the vastai CLI: the CLI
exits 0 even on HTTP errors and prints nothing on stdout then
(gpu-resilience-research.md B §2), so its exit code proves nothing.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from urllib.parse import quote_plus

API = "https://console.vast.ai"


class Rejected(Exception):
    """Vast answered with an error (4xx): the request did nothing."""


class Uncertain(Exception):
    """No usable answer (network, timeout, 5xx): it may or may not have
    taken effect, so the caller must find out before acting again."""


def call(method: str, path: str, body=None, query: dict | None = None):
    url = API + path
    if query:
        url += "?" + "&".join(f"{k}={quote_plus(v if isinstance(v, str) else json.dumps(v))}"
                              for k, v in query.items())
    req = urllib.request.Request(
        url, method=method, data=None if body is None else json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {os.environ['VAST_API_KEY']}",
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        detail = f"HTTP {e.code} {e.read()[:300].decode(errors='replace')}"
        raise (Uncertain if e.code >= 500 else Rejected)(detail) from e
    except (OSError, ValueError) as e:  # no connection, timeout, garbled answer
        raise Uncertain(repr(e)) from e


def instances() -> list[dict]:
    """Every instance of the account. Raises rather than return a partial
    list: a missing row is read as "gone"."""
    rows, query = [], {"select_filters": {}, "order_by": [{"col": "id", "dir": "asc"}],
                       "limit": 25}
    while True:
        page = call("GET", "/api/v1/instances/", query=query)
        if not page.get("success", True) or "instances" not in page:
            raise Uncertain(f"odd instance list: {str(page)[:200]}")
        rows += page["instances"] or []
        if not page.get("next_token"):
            return rows
        query["after_token"] = page["next_token"]


def offers(query: dict) -> list[dict]:
    return call("POST", "/api/v0/bundles/", query)["offers"]


def create(offer_id: int, payload: dict) -> int:
    """Rent an offer; the new instance id. Uncertain when Vast's answer
    lacks one: an instance may exist anyway (its label finds it)."""
    answer = call("PUT", f"/api/v0/asks/{offer_id}/", payload)
    if not answer.get("new_contract"):
        raise Uncertain(f"no instance id in {str(answer)[:200]}")
    return int(answer["new_contract"])


def destroy(instance_id: int) -> None:
    call("DELETE", f"/api/v0/instances/{instance_id}/", {})


def guards() -> list[dict]:
    """The account's scheduled jobs (here: deletion guards)."""
    return call("GET", "/api/v0/commands/schedule_job/")


def guard_target(guard: dict) -> int | None:
    """Instance id a scheduled DELETE destroys, or None for other jobs."""
    path = guard.get("api_endpoint") or ""
    if guard.get("request_method") != "DELETE" or not path.startswith("/api/v0/instances/"):
        return None
    return int(path.strip("/").rsplit("/", 1)[1])


def add_guard(instance_id: int, at: float) -> int:
    """Have Vast's own servers DELETE the instance from the first full hour
    after ``at`` on, hourly until it is gone, with or without the web app;
    the guard's id.

    Vast runs an HOURLY job at minute 0 of every hour from the hour that
    *contains* start_time (probes 2026-10-03: start 13:22 ran at 13:00),
    so the start goes just past the next full hour. Setting
    min_of_the_hour afterwards stopped a job from running at all.
    """
    start = -(-int(at) // 3600) * 3600 + 1
    return int(call("POST", "/api/v0/commands/schedule_job/", {
        "start_time": start, "end_time": start + 24 * 3600,
        "api_endpoint": f"/api/v0/instances/{instance_id}/", "request_method": "DELETE",
        "request_body": {}, "day_of_the_week": None, "hour_of_the_day": None,
        "frequency": "HOURLY", "instance_id": instance_id})["scheduled_job_id"])


def remove_guard(guard_id: int) -> None:
    call("DELETE", f"/api/v0/commands/schedule_job/{guard_id}/")


def audit_log() -> list[dict]:
    return call("GET", "/api/v0/audit_logs/")


def failure(row: dict) -> str | None:
    """Why a listed instance will never run, or None (rule in research B §2).

    A null actual_status is a row still provisioning, not a failure.
    """
    actual, intended = row.get("actual_status"), row.get("intended_status")
    if intended == "stopped" or actual in ("exited", "stopped", "unknown", "offline"):
        return f"Vast reports it {actual} (meant to be {intended})"
    msg = (row.get("status_msg") or "").lower()
    if any(t in msg for t in ("error", "failed", "exception", "oci runtime",
                              "permission denied")):
        return f"failed to start: {row['status_msg'][:200]}"
    return None
