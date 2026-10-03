"""Mocked checks of the cloud GPU job state machine: coordinator.py,
jobs.py and the web app's job requests (serve.py), against fake buckets
that do S3's conditional writes and a fake Vast.ai with injectable
failures.

    uv run --with boto3 python checks/gpu-jobs.py

Each check asserts on rentals, guards and records, not just that a job
finishes. What only real rentals can show (Vast's timings, the worker on a
host) is in gpu-resilience-handoff.md, "Verifying the implementation".
"""

import hashlib
import http.client
import io
import json
import os
import socket
import tempfile
import threading
import time
import types
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path

from botocore.exceptions import ClientError  # ty: ignore[unresolved-import]

os.environ.update(VAST_API_KEY="v", JOBS_ACCESS_KEY="j", JOBS_SECRET_KEY="j",
                  S3_ACCESS_KEY="w", S3_SECRET_KEY="w")
os.environ.pop("CREATE_PASSWORDS", None)

from drum_transcribe import (
    coordinator,
    gate,
    ingest,
    jobs,
    progress,
    serve,
    vast,
)

SONG = "song"
T0 = 1_800_000_000.0


def patch(module, **attrs):
    """Swap module attributes for fakes (the code under test calls them
    through the module)."""
    for name, value in attrs.items():
        setattr(module, name, value)


class S3:
    """Both buckets in one dict, with Scaleway's 412 for a failed
    If-Match / If-None-Match."""

    def __init__(self):
        self.objs: dict[tuple[str, str], bytes] = {}
        self.fail_puts = 0

    @staticmethod
    def etag(body: bytes) -> str:
        return f'"{hashlib.md5(body).hexdigest()}"'

    def put_object(self, Bucket, Key, Body, IfMatch=None, IfNoneMatch=None, **_):
        if self.fail_puts:
            self.fail_puts -= 1
            raise ClientError({"Error": {"Code": "InternalError"}}, "PutObject")
        cur = self.objs.get((Bucket, Key))
        if (IfNoneMatch == "*" and cur is not None) or (
                IfMatch and (cur is None or self.etag(cur) != IfMatch)):
            raise ClientError({"Error": {"Code": "PreconditionFailed"}}, "PutObject")
        self.objs[Bucket, Key] = bytes(Body)
        return {"ETag": self.etag(bytes(Body))}

    def get_object(self, Bucket, Key):
        if (Bucket, Key) not in self.objs:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        body = self.objs[Bucket, Key]
        return {"Body": io.BytesIO(body), "ETag": self.etag(body)}

    def list_objects_v2(self, Bucket, Prefix=""):
        found = [{"Key": k, "ETag": self.etag(b)} for (bk, k), b in sorted(self.objs.items())
                 if bk == Bucket and k.startswith(Prefix)]
        return {"Contents": found} if found else {}

    def get_paginator(self, _):
        return types.SimpleNamespace(paginate=lambda **kw: [self.list_objects_v2(**kw)])

    def delete_object(self, Bucket, Key):
        self.objs.pop((Bucket, Key), None)

    def copy_object(self, Bucket, Key, CopySource):
        self.objs[Bucket, Key] = self.objs[CopySource["Bucket"], CopySource["Key"]]

    def upload_file(self, path, Bucket, Key):
        self.objs[Bucket, Key] = Path(path).read_bytes()

    def download_file(self, Bucket, Key, path):
        if (Bucket, Key) not in self.objs:
            raise ClientError({"Error": {"Code": "404"}}, "HeadObject")
        Path(path).write_bytes(self.objs[Bucket, Key])

    def keys(self, bucket, prefix=""):
        return [k for b, k in self.objs if b == bucket and k.startswith(prefix)]


class Vast:
    """The account: instances, scheduled DELETEs, audit log, offers."""

    def __init__(self, clock):
        self.clock, self.rows, self.guard_jobs, self.log = clock, {}, {}, []
        self.created, self.destroyed, self.queries = [], [], []
        self.ids, self.gids = iter(range(1000, 2000)), iter(range(1, 1000))
        self.create_mode = self.guard_mode = self.destroy_mode = None
        self.offer_list = [{"id": 70 + i, "machine_id": 500 + i, "host_id": 9,
                            "public_ipaddr": f"10.0.0.{i}", "min_bid": .1, "dph_base": .1,
                            "dph_total": .115, "inet_down": 900, "inet_down_cost": 0,
                            "inet_up_cost": 0, "geolocation": "XX"} for i in range(8)]

    def instances(self):
        return [dict(r) for r in self.rows.values()]

    def guards(self):
        return [dict(g) for g in self.guard_jobs.values()]

    def offers(self, q):
        self.queries.append(q)
        out = self.offer_list
        for field in ("machine_id", "public_ipaddr"):
            if field in q:
                out = [o for o in out if o[field] not in q[field]["notin"]]
        return [dict(o) for o in out]

    def create(self, offer_id, payload):
        if self.create_mode == "refuse":
            raise vast.Rejected("HTTP 410 no_such_ask")
        offer = next(o for o in self.offer_list if o["id"] == offer_id)
        iid = next(self.ids)
        self.rows[iid] = {"id": iid, "label": payload["label"], "actual_status": None,
                          "intended_status": "running", "status_msg": None,
                          **{k: offer[k] for k in ("machine_id", "host_id", "public_ipaddr")}}
        self.created.append((iid, payload))
        self.log.append({"api_route": "api.ask_PUT", "created_at": self.clock.now,
                         "args": {"contract_id": iid}})
        if self.create_mode == "lost":
            raise vast.Uncertain("timed out")
        return iid

    def destroy(self, iid):
        if self.destroy_mode == "fail":
            raise vast.Uncertain("timed out")
        self.destroyed.append(iid)
        self.rows.pop(iid, None)

    def add_guard(self, iid, at):
        if self.guard_mode == "refuse":
            raise vast.Rejected("HTTP 400")
        if self.guard_mode != "lost-none":
            gid = next(self.gids)
            self.guard_jobs[gid] = {"id": gid, "api_endpoint": f"/api/v0/instances/{iid}/",
                                    "request_method": "DELETE", "start_time": at}
        if self.guard_mode in ("lost", "lost-none"):
            raise vast.Uncertain("timed out")
        return gid

    def remove_guard(self, gid):
        self.guard_jobs.pop(gid, None)

    def audit_log(self):
        return list(self.log)

    def fire_guards(self):
        """Vast's scheduler: due DELETEs run, whoever else is gone."""
        for g in self.guard_jobs.values():
            if g["start_time"] <= self.clock.now:
                self.rows.pop(vast.guard_target(g), None)

    def run(self, iid, status="running"):
        self.rows[iid]["actual_status"] = status


class World:
    def __init__(self):
        self.clock = types.SimpleNamespace(now=T0)
        self.s3, self.vast = S3(), Vast(self.clock)
        self.root = Path(tempfile.mkdtemp())
        self.storage(self.s3)
        jobs._cache.clear()
        jobs._known.clear()
        self.account(self.vast)
        patch(coordinator, wake=lambda: None, time=types.SimpleNamespace(
            time=lambda: self.clock.now, strftime=time.strftime, gmtime=time.gmtime))
        for state in (coordinator._absent, coordinator._preparing, coordinator._prep_failed,
                      coordinator._seen, coordinator._pushed):
            state.clear()
        patch(ingest, prepare=self.prepare)
        self.bad_inputs = set()

    def storage(self, s3):
        self.s3 = s3
        patch(jobs, _s3=lambda: s3)
        patch(gate, results_bucket=lambda: (s3, "results"))

    def account(self, fake):
        self.vast = fake
        patch(vast, **{name: getattr(fake, name) for name in (
            "instances", "guards", "offers", "create", "destroy", "add_guard",
            "remove_guard", "audit_log")})

    def prepare(self, vdir, rec):
        """Stands in for fetching: publishes the source, or fails."""
        if rec["url"] in self.bad_inputs:
            raise RuntimeError("video unavailable")
        self.s3.objs["results", f"sources/{rec['job']}/source.mp3"] = b"audio"

    def submit(self, version="v1", url="https://example.com/a.mp3"):
        jobs.save(jobs.new(SONG, version, url=url), None)

    def rec(self, version="v1") -> dict:
        rec, _ = jobs.load(SONG, version)
        assert rec is not None
        return rec

    def tick(self, minutes=1.0, passes=1):
        for _ in range(passes):
            self.clock.now += minutes * 60
            coordinator.reconcile(self.root)
            for t in list(coordinator._preparing.values()):
                t.join()

    def worker_done(self, variants, gen=1, version="v1", claim=None):
        """What a worker leaves in the results bucket."""
        prefix = f"{SONG}/{version}/"
        self.s3.objs["results", prefix + "source.mp3"] = b"audio"
        for v in variants:
            self.s3.objs["results", f"{prefix}{v}/events.json"] = json.dumps(
                {"meter": 4, "events": []}).encode()
            self.s3.objs["results", f"{prefix}{v}/sonification.ogg"] = b"ogg"
            self.s3.objs["results", f"{prefix}{v}/done"] = f"{gen}\n".encode()
        if claim:
            self.s3.objs["results", f"{prefix}workers/{claim}.log"] = b"all variants uploaded\n"

    def live(self):
        return [r for r in self.vast.rows.values()]


def attempt(rec, i=-1):
    return rec["attempts"][i]


# ---- checks ---------------------------------------------------------------

def check_one_rental_per_job():
    w = World()
    w.submit()
    try:
        w.submit()
        raise AssertionError("a second record for one version was accepted")
    except jobs.Conflict:
        pass
    w.tick(passes=4)
    assert len(w.vast.created) == 1, w.vast.created
    rec = w.rec()
    assert rec["source"] == f"sources/{rec['job']}/source.mp3"
    assert ("results", f"{SONG}/v1/source.mp3") in w.s3.objs  # the page plays it from there
    assert len(w.vast.guard_jobs) == 1  # guarded right after creation
    # two coordinators (an overlapping deployment) with the same old record:
    w2 = World()
    w2.submit()
    a, b = jobs.records(), jobs.records()
    coordinator._Job(coordinator._Pass(w2.root, a), *a[0]).step()
    try:
        coordinator._Job(coordinator._Pass(w2.root, b), *b[0]).step()
        raise AssertionError("a stale coordinator went ahead")
    except jobs.Conflict:
        pass
    assert len(w2.vast.created) == 1


def check_failed_write_rents_nothing():
    w = World()
    w.submit()
    w.vast.offer_list, offers = [], w.vast.offer_list
    w.tick(passes=2)  # recording published, nothing on offer
    assert "no suitable" in w.rec()["status"].lower() or "price" in w.rec()["status"].lower()
    w.vast.offer_list = offers
    w.s3.fail_puts = 1  # the claim can't be saved
    w.tick()
    assert not w.vast.created and not w.rec()["attempts"]
    w.tick()
    assert len(w.vast.created) == 1


def fail_current(w):
    """The running rental dies: Vast reports it exited."""
    iid = attempt(w.rec())["instance"]
    w.vast.run(iid, "exited")
    w.tick(passes=2)


def check_five_rentals_then_failed_and_caps_survive_restart():
    w = World()
    w.submit()
    w.tick()
    for _ in range(5):
        fail_current(w)
    rec = w.rec()
    assert len(w.vast.created) == 5, len(w.vast.created)
    assert rec["state"] == "failed", rec["state"]
    assert [a["type"] for a in rec["attempts"]] == ["bid"] * 4 + ["fixed"]
    assert w.vast.created[-1][1]["price"] is None  # fixed price: no bid
    assert not w.live() and not w.vast.guard_jobs
    w2 = World()  # restart: nothing in memory, same storage
    w2.storage(w.s3)
    w2.account(w.vast)
    w2.root = w.root
    w2.tick(passes=3)
    assert len(w.vast.created) == 5


def check_daily_cap():
    w = World()
    other = jobs.new(SONG, "busy")
    other["state"] = "done"
    other["attempts"] = [{"claim": str(i), "label": f"x/{i}", "generation": 1,
                          "create": "created", "claimed": T0, "closed": T0,
                          "instance": i} for i in range(30)]
    jobs.save(other, None)
    w.submit()
    w.tick(passes=2)
    assert not w.vast.created
    assert "daily" in w.rec()["status"].lower()
    w.tick(minutes=24 * 60)  # the next UTC day
    assert len(w.vast.created) == 1


def check_lost_create_found_by_label():
    w = World()
    w.submit()
    w.vast.create_mode = "lost"
    w.tick()
    assert len(w.vast.created) == 1 and attempt(w.rec())["instance"] is None
    w.vast.create_mode = None
    w.tick(passes=3)
    rec = w.rec()
    assert len(w.vast.created) == 1, "created again while the first was unknown"
    assert attempt(rec)["instance"] == w.vast.created[0][0]
    assert len(w.vast.guard_jobs) == 1


def check_lost_create_already_gone_resolved_by_audit_log():
    w = World()
    w.submit()
    w.vast.create_mode = "lost"
    w.tick()
    w.vast.create_mode = None
    w.vast.rows.clear()  # it died before anyone saw it
    w.tick(passes=5)  # < 10 min: never create while the outcome is unknown
    assert len(w.vast.created) == 1
    assert "checking" in w.rec()["status"].lower()
    w.tick(minutes=6, passes=3)  # the audit log names it; Vast doesn't list it
    rec = w.rec()
    assert rec["attempts"][0]["closed"] and rec["attempts"][0]["instance"] == 1000
    assert len(w.vast.created) == 2


def check_claim_without_create_waits_for_audit_log():
    """A crash between saving the claim and calling Vast."""
    w = World()
    w.submit()
    rec, etag = w.rec(), jobs.load(SONG, "v1")[1]
    rec["attempts"].append({"claim": "c0", "label": "drum-transcribe/x/c0", "generation": 1,
                            "try": 1, "type": "bid", "claimed": T0, "deadline": T0 + 2400,
                            "create": "claimed", "instance": None})
    jobs.save(rec, etag)
    w.tick(passes=8)
    assert not w.vast.created, "rented while a claim was unresolved"
    w.tick(minutes=5, passes=2)
    rec = w.rec()
    assert rec["attempts"][0]["outcome"].startswith("no rental was created")
    assert len(w.vast.created) == 1
    assert rec["attempts"][1]["try"] == 2  # the unresolved claim counted


def check_guard_answers_lost():
    for mode, guards in (("lost", 1), ("lost-none", 1)):
        w = World()
        w.submit()
        w.vast.guard_mode = mode
        w.tick()
        w.vast.guard_mode = None
        w.tick(passes=3)
        assert len(w.vast.guard_jobs) == guards, (mode, w.vast.guard_jobs)
        assert len(w.vast.created) == 1


def check_guard_refused_destroys():
    w = World()
    w.submit()
    w.vast.guard_mode = "refuse"
    w.tick()
    assert w.vast.destroyed == [1000]
    assert len(w.vast.created) == 1  # no replacement until it is confirmed gone
    w.vast.guard_mode = None
    w.tick(passes=2)
    rec = w.rec()
    assert rec["attempts"][0]["outcome"].startswith("could not schedule")
    assert len(w.vast.created) == 2


def check_done_job_cleanup_keeps_guard_until_gone():
    w = World()
    w.submit()
    w.tick()
    rec = w.rec()
    iid, claim = attempt(rec)["instance"], attempt(rec)["claim"]
    w.vast.run(iid)
    w.tick()
    w.vast.destroy_mode = "fail"  # the worker's DELETE and ours both fail
    w.worker_done(rec["variants"], claim=claim)
    w.tick()
    rec = w.rec()
    assert rec["state"] == "done" and attempt(rec)["ending"] == "finished"
    assert (w.root / SONG / "v1" / "adtof" / "events.json").exists()
    w.tick(passes=3)
    assert iid in w.vast.rows and len(w.vast.guard_jobs) == 1, "guard removed too early"
    assert jobs.unsettled(w.rec())
    w.clock.now = attempt(rec)["deadline"]
    w.vast.fire_guards()  # Vast's scheduled DELETE ends it
    w.tick()
    rec = w.rec()
    assert not jobs.unsettled(rec) and not w.vast.guard_jobs
    assert len(w.vast.created) == 1


def check_startup_deadline_and_blocklists():
    w = World()
    w.submit()
    w.tick()
    first = attempt(w.rec())
    w.tick(minutes=16)  # still loading the image
    assert w.vast.destroyed == [first["instance"]]
    w.tick()
    rec = w.rec()
    assert rec["attempts"][0]["outcome"] == "the image did not load in time"
    assert first["machine_id"] in w.vast.queries[-1]["machine_id"]["notin"]
    # a host whose worker found the bucket too slow, then deleted itself
    second = attempt(rec)
    w.vast.run(second["instance"])
    w.tick()
    w.s3.objs["results", f"{SONG}/v1/workers/{second['claim']}.log"] = (
        b"== fetching the recording ==\nbucket too slow from this host\n")
    w.tick()
    w.vast.rows.pop(second["instance"])
    w.tick(passes=2)
    rec = w.rec()
    assert rec["attempts"][1]["outcome"] == "slow bucket link", rec["attempts"][1]
    assert second["public_ipaddr"] in w.vast.queries[-1]["public_ipaddr"]["notin"]


def check_bad_input_fails_once():
    w = World()
    w.bad_inputs.add("https://example.com/gone")
    w.submit(url="https://example.com/gone")
    w.tick(passes=4)
    rec = w.rec()
    assert rec["state"] == "failed" and "recording" in rec["status"]
    assert len(w.vast.created) <= 1 and not w.live()


def check_stray_instances_swept():
    w = World()
    w.vast.rows[1] = {"id": 1, "label": "drum-transcribe/gone/x", "actual_status": "running"}
    w.vast.rows[2] = {"id": 2, "label": "my manual test", "actual_status": "running"}
    w.vast.guard_jobs[5] = {"id": 5, "api_endpoint": "/api/v0/instances/77/",
                            "request_method": "DELETE", "start_time": T0}
    w.tick(passes=2)
    assert w.vast.destroyed == [1] and 2 in w.vast.rows
    assert not w.vast.guard_jobs


def check_progress_reads_the_record():
    w = World()
    w.submit()
    w.tick()
    vdir = w.root / SONG / "v1"
    rec = w.rec()
    p = progress.version_progress(vdir, False, rec)
    assert p["job"] == "running" and "gpu" in p["tasks"], p
    rec["state"] = "failed"
    assert progress.version_progress(vdir, False, rec)["job"] == "failed"


# ---- the web app's requests ----------------------------------------------

def server(w):
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), partial(serve.AppHandler, root=w.root))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd.server_address[1]


def post(port, path, body):
    c = http.client.HTTPConnection("127.0.0.1", port)
    c.request("POST", path, json.dumps(body), {"Content-Type": "application/json"})
    r = c.getresponse()
    return r.status, json.loads(r.read() or b"{}")


def check_requests():
    w = World()
    port = server(w)
    status, _ = post(port, "/api/create", {"project": SONG, "version": "v1",
                                           "url": "https://example.com/a.mp3", "gpu": True})
    assert status == 200 and w.rec()["url"] == "https://example.com/a.mp3"
    status, d = post(port, "/api/create", {"project": SONG, "version": "v1",
                                           "url": "https://example.com/b.mp3", "gpu": True})
    assert status == 400, d
    for path, body in (("/api/rawbars", {"raw": True}), ("/api/delete", {}),
                       ("/api/retry", {})):
        status, d = post(port, path, {"project": SONG, "version": "v1", **body})
        assert status == 400, (path, d)
    w.tick()
    rec = w.rec()
    iid = attempt(rec)["instance"]
    w.vast.run(iid)
    w.worker_done(rec["variants"])
    w.tick()
    status, _ = post(port, "/api/rawbars", {"project": SONG, "version": "v1", "raw": True})
    assert status == 400, "meter changed with a rental unsettled"
    w.tick(passes=2)  # the finished rental is destroyed and confirmed gone
    status, d = post(port, "/api/rawbars", {"project": SONG, "version": "v1", "raw": True})
    assert status == 200, d
    rec = w.rec()
    assert rec["generation"] == 2 and rec["raw_bars"] and rec["state"] == "open"
    w.tick(passes=2)  # generation-1 markers must not finish generation 2
    rec = w.rec()
    assert rec["state"] == "open" and rec["done"] == []
    payload = w.vast.created[-1][1]
    assert payload["env"]["GENERATION"] == "2" and payload["env"]["RAW_BARS"] == "1"
    w.worker_done(rec["variants"], gen=2)
    w.tick(passes=3)
    assert w.rec()["state"] == "done" and not jobs.unsettled(w.rec())
    status, d = post(port, "/api/delete", {"project": SONG, "version": "v1"})
    assert status == 200, d
    assert jobs.load(SONG, "v1") == (None, None) and not (w.root / SONG / "v1").exists()

    # uploads: only a complete body becomes a job, and its original is stored first
    with socket.create_connection(("127.0.0.1", port)) as s:
        s.sendall(b"PUT /api/upload?project=song&version=cut&filename=a.mp3&gpu=1 HTTP/1.1\r\n"
                  b"Host: x\r\nContent-Length: 1000\r\n\r\n" + b"x" * 400)
        s.shutdown(socket.SHUT_WR)
        reply = s.recv(4096).decode()
    assert " 400 " in reply.split("\r\n")[0], reply
    assert jobs.load(SONG, "cut") == (None, None) and not (w.root / SONG / "cut").exists()
    c = http.client.HTTPConnection("127.0.0.1", port)
    c.request("PUT", "/api/upload?project=song&version=up&filename=a.mp3&gpu=1", b"x" * 1000)
    assert c.getresponse().status == 200
    rec = w.rec("up")
    assert w.s3.objs["results", rec["upload"]] == b"x" * 1000


def main():
    checks = [(n, f) for n, f in globals().items() if n.startswith("check_")]
    for name, f in checks:
        f()
        print(f"ok  {name}", flush=True)
    print(f"all {len(checks)} checks passed")


if __name__ == "__main__":
    main()
