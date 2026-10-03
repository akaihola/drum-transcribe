"""The one owner of cloud GPU rentals: a thread that reconciles the trusted
job records (jobs.py) with what Vast.ai and the results bucket say.

Runs only in the cloud web app (jobs.enabled()): at startup, then once a
minute while the container is up. Requests that change a job wake it;
they never rent themselves. Each pass lists the account's instances and
deletion guards once, then per job:

1. starts fetching the recording, or records it as published;
2. fetches the variants whose done marker names the current generation;
3. settles every rental: finds a created instance by its label, guards it
   with a Vast-side scheduled DELETE, destroys it once unwanted or
   overdue, and closes it once Vast no longer lists it;
4. rents again if work is left, no rental is unsettled and the caps allow.

A rental is claimed in the record before Vast is asked for it; a failed
record write means no rental. A create whose outcome is unknown is never
repeated: later passes look for its label, then for its creation in the
account's audit log. Only instance ids Vast itself lists are destroyed;
nothing read from the results bucket is an instruction.

honey: one coordinator process with max_scale 1; add ownership fencing
before increasing scale or allowing overlapping deployments.
"""

from __future__ import annotations

import os
import random
import re
import threading
import time
import uuid
from pathlib import Path

from . import gate, ingest, jobs, vast
from .ingest import AUDIO_EXTS, marker

IMAGE = "ghcr.io/akaihola/drum-transcribe-gpu:2026-10-03"
LABEL = "drum-transcribe/"  # every rental is <LABEL><job>/<claim>; others aren't ours
TRIES = 5                   # rentals per generation: 1-4 bid, the 5th at a fixed price
DAILY = 30                  # rentals per UTC day, all songs together
BID = 1.25                  # times the going rate: 1.15 got outbid before the start
STARTUP = 15 * 60           # s from the claim until the instance must be running
ATTEMPT = 30 * 60           # s from the claim until the worker's own deadline
GUARD_DELAY = 60 * 60       # s after the deadline Vast's scheduled DELETE may take
MAX_HOURLY = 0.18           # $/h with the disk: the dearest offer taken (decided 2026-10-03)
TRANSFER_GB = 0.2           # recording down, results up, on hosts that bill bandwidth
# hours a rental can bill if its worker and this app both fail to end it
# (+5 min: Vast's billing outlasts a delete)
WORST_HOURS = (ATTEMPT + GUARD_DELAY + 300) / 3600
QUERY = {"verified": {"eq": True}, "external": {"eq": False}, "rentable": {"eq": True},
         "rented": {"eq": False}, "gpu_name": {"eq": "RTX 3090"}, "num_gpus": {"eq": 1},
         "reliability": {"gt": 0.98}, "inet_down": {"gt": 500},
         # the base image's CUDA; 12.8 drivers hit error 804 on GeForce cards
         "cuda_max_good": {"gte": 12.9},
         "allocated_storage": 40, "order": [["dph_total", "asc"]]}
# outcomes that rule a machine, or a whole site (address), out for a week
BAD_MACHINE = ("broken GPU", "deadline passed", "the image did not load in time",
               "failed to start")
BAD_SITE = ("slow bucket link",)

CHECKING = "Checking what became of the previous rental before renting another"

WAKE = threading.Event()
_absent: dict[int, int] = {}          # instance id -> passes in a row Vast didn't list it
_preparing: dict[str, threading.Thread] = {}  # job id -> thread fetching its recording
_prep_failed: dict[str, str] = {}     # job id -> why its recording couldn't be had
_seen: dict[str, str] = {}            # results-bucket key -> etag already in output/
_pushed: dict[str, float] = {}        # job id -> mtime of its log last saved
# kept by the web app itself; a worker must not overwrite them
LOCAL = {"created", "source-url.txt", "keep-raw-bars", "feedback.json"}


def start(root: Path) -> None:
    threading.Thread(target=_loop, args=(root,), daemon=True, name="coordinator").start()


def wake() -> None:
    WAKE.set()


def _loop(root: Path) -> None:
    while True:
        WAKE.clear()
        try:
            reconcile(root)
        except Exception as e:  # noqa: BLE001 - the next pass tries again
            print(f"coordinator: pass failed: {e!r}", flush=True)
        WAKE.wait(60)


def reconcile(root: Path) -> None:
    p = _Pass(root, jobs.records())
    for rec, etag in p.recs:
        job = _Job(p, rec, etag)
        try:
            job.step()
        except jobs.Conflict:
            pass  # a request changed it meanwhile; the next pass sees how
        except Exception as e:  # noqa: BLE001 - one job's trouble mustn't stop the rest
            job.log(f"   coordinator: {e!r}")
        job.push_log()
    if p.vast_ok:
        p.sweep()


class _Pass:
    """What one pass knows: the records, and Vast's instances and guards."""

    def __init__(self, root: Path, recs: list[tuple[dict, str]]):
        self.root, self.recs, self._audit = root, recs, None
        try:
            rows, self.guards = vast.instances(), vast.guards()
            self.vast_ok = True
        except (vast.Uncertain, vast.Rejected) as e:
            print(f"coordinator: no answer from Vast ({e}); rentals wait", flush=True)
            rows, self.guards, self.vast_ok = [], [], False
        self.rows = {r["id"]: r for r in rows}
        self.by_label = {r["label"]: r for r in rows if (r.get("label") or "").startswith(LABEL)}

    def audit(self) -> list[dict]:
        if self._audit is None:
            self._audit = vast.audit_log()
        return self._audit

    def sweep(self) -> None:
        """Destroy our labelled instances that no open rental accounts for
        (e.g. their version was deleted), and drop deletion guards whose
        instance Vast has stopped listing."""
        open_ = {a["label"]: a for rec, _ in self.recs for a in rec["attempts"]
                 if not a.get("closed")}
        for label, row in self.by_label.items():
            if label not in open_:
                print(f"coordinator: destroying stray instance {row['id']} ({label})", flush=True)
                _try(vast.destroy, row["id"])
        watched = {a.get("instance") for a in open_.values()}
        for g in self.guards:
            target = vast.guard_target(g)
            if target is None or target in self.rows or target in watched:
                continue
            _absent[target] = _absent.get(target, 0) + 1
            if _absent[target] >= 2:  # gone, not just missing from one answer
                _try(vast.remove_guard, g["id"])


class _Job:
    def __init__(self, p: _Pass, rec: dict, etag: str):
        self.p, self.rec, self.etag = p, rec, etag
        self.vdir = p.root / rec["song"] / rec["version"]

    def save(self) -> None:
        self.etag = jobs.save(self.rec, self.etag)

    def log(self, line: str) -> None:
        self.vdir.mkdir(parents=True, exist_ok=True)
        ingest._log(self.vdir, line)

    def status(self, text: str) -> None:
        if self.rec["status"] != text:
            self.rec["status"] = text
            self.save()

    def fail(self, why: str) -> None:
        self.rec["state"], self.rec["status"] = "failed", why
        self.save()
        self.log(f"ERROR: {why}")

    def step(self) -> None:
        log = self.vdir / "pipeline.log"
        if self.rec["job"] not in _pushed:  # first sight since the container started
            if not log.exists():
                self.vdir.mkdir(parents=True, exist_ok=True)
                jobs.pull_log(self.rec["song"], self.rec["version"], log)
            _pushed[self.rec["job"]] = log.stat().st_mtime if log.exists() else 0
        if self.rec["state"] == "open":
            self.prepare()
        if self.rec["state"] == "open":
            self.collect()
        if self.p.vast_ok:
            for a in self.rec["attempts"]:
                if not a.get("closed"):
                    self.settle(a)
            if self.rec["state"] == "open" and not jobs.unsettled(self.rec):
                self.rent()

    def push_log(self) -> None:
        log = self.vdir / "pipeline.log"
        if log.exists() and _pushed.get(self.rec["job"]) != (mtime := log.stat().st_mtime):
            jobs.push_log(self.rec["song"], self.rec["version"], log)
            _pushed[self.rec["job"]] = mtime

    # ---- the recording ------------------------------------------------

    def prepare(self) -> None:
        rec = self.rec
        if rec["source"]:
            return
        s3, bucket = gate.results_bucket()
        published = s3.list_objects_v2(Bucket=bucket, Prefix=f"sources/{rec['job']}/source.")
        if published.get("Contents"):
            key = published["Contents"][0]["Key"]
            # beside the results too: the page plays the original from there,
            # also after a cold start, long before the first variant is up
            s3.copy_object(Bucket=bucket, CopySource={"Bucket": bucket, "Key": key},
                           Key=f"{rec['song']}/{rec['version']}/{key.rsplit('/', 1)[1]}")
            rec["source"] = key
            self.save()
            return
        if why := _prep_failed.pop(rec["job"], None):
            self.fail(f"could not get the recording: {why}")
            return
        thread = _preparing.get(rec["job"])
        if thread is None or not thread.is_alive():
            thread = threading.Thread(target=_prepare, args=(self.vdir, dict(rec)), daemon=True)
            _preparing[rec["job"]] = thread
            thread.start()

    # ---- results ------------------------------------------------------

    def collect(self) -> None:
        """Fetch what the worker finished into output/: a variant once its
        done marker names this generation, the shared files (recording,
        beat grid, stems) with the first, the attempt logs as they come.
        Audio becomes an empty stand-in the page fetches from the bucket."""
        rec = self.rec
        s3, bucket = gate.results_bucket()
        prefix = f"{rec['song']}/{rec['version']}/"
        objs = [o for page in s3.get_paginator("list_objects_v2").paginate(
            Bucket=bucket, Prefix=prefix) for o in page.get("Contents", [])]
        keys = {o["Key"] for o in objs}
        done = [v for v in rec["variants"] if f"{prefix}{v}/done" in keys and s3.get_object(
            Bucket=bucket, Key=f"{prefix}{v}/done")["Body"].read().strip()
            == str(rec["generation"]).encode()]
        root = self.vdir.resolve()
        for o in objs:
            rel = o["Key"][len(prefix):]
            top = rel.split("/", 1)[0]
            if (Path(rel).name in LOCAL or rel.endswith("/done") or _seen.get(o["Key"]) == o["ETag"]
                    or (top in rec["variants"] and top not in done)
                    or (top not in rec["variants"] and top != "workers" and not done)):
                continue
            path = (root / rel).resolve()
            if not path.is_relative_to(root):  # a rented host wrote this name
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.suffix not in AUDIO_EXTS:
                s3.download_file(bucket, o["Key"], str(path))
            elif not path.exists() or not path.stat().st_size:
                path.touch()  # a new stand-in, or a newer version of one
            _seen[o["Key"]] = o["ETag"]
        if done != rec["done"]:
            new = [v for v in done if v not in rec["done"]]
            rec["done"] = done
            if set(done) >= set(rec["variants"]):
                rec["state"], rec["status"] = "done", ""
            self.save()
            for v in new:
                self.log(f"   {v} is ready")
            if rec["state"] == "done":
                self.log(marker("all pipelines finished"))

    # ---- rentals ------------------------------------------------------

    def settle(self, a: dict) -> None:
        if a.get("instance") is None and not self.find(a):
            return
        iid = a["instance"]
        row = self.p.rows.get(iid)
        if row is None:
            _absent[iid] = _absent.get(iid, 0) + 1
            # a fresh instance may be missing from one answer; once seen, gone is gone
            if a.get("seen") or _absent[iid] >= 2:
                self.close(a)
            return
        _absent.pop(iid, None)
        changed = False
        if not a.get("seen"):
            a["seen"] = True
            a.update({k: row.get(k) for k in ("machine_id", "host_id", "public_ipaddr")})
            changed = True
        if row.get("actual_status") == "running" and not a.get("running"):
            a["running"] = time.time()
            self.log(f"   instance running, {round(a['running'] - a['claimed'])} s after renting")
            changed = True
        if changed:
            self.save()
        self.guard(a)
        if why := self.overdue(a, row):
            if not a.get("ending"):
                a["ending"] = why
                self.save()
                self.log(f"   ending instance {iid}: {why}")
            _try(vast.destroy, iid)

    def find(self, a: dict) -> bool:
        """The instance of a claim whose create got no clear answer: by its
        label, else from the audit log. False while that stays unknown."""
        if row := self.p.by_label.get(a["label"]):
            a["instance"] = row["id"]
            self.save()
            self.log(f"   found the rental by its label: instance {row['id']}")
            return True
        self.status(CHECKING)
        if time.time() - a["claimed"] < 600:
            return False  # a create sent just before a crash may still land
        try:
            log = self.p.audit()
        except (vast.Uncertain, vast.Rejected) as e:
            self.log(f"   cannot read Vast's audit log yet ({e})")
            return False
        known = {b.get("instance") for rec, _ in self.p.recs for b in rec["attempts"]}
        made = [e["args"]["contract_id"] for e in log
                if e.get("api_route") == "api.ask_PUT" and e["created_at"] >= a["claimed"] - 60
                and e["args"].get("contract_id") not in known
                # one Vast still lists bears another label: not this claim's
                and e["args"]["contract_id"] not in self.p.rows]
        if made:
            a["instance"] = made[0]
            self.save()
            self.log(f"   the audit log shows the rental: instance {made[0]}")
            return True
        a["closed"], a["outcome"] = time.time(), "no rental was created (audit log)"
        self.save()
        self.log("   the audit log shows no rental was created")
        return False

    def guard(self, a: dict) -> None:
        """Make sure Vast itself deletes the instance after the deadline,
        even if this container and the worker are both gone by then."""
        iid = a["instance"]
        if a.get("ending") or any(vast.guard_target(g) == iid for g in self.p.guards):
            return
        try:
            a["guard"] = vast.add_guard(iid, a["deadline"])
        except vast.Uncertain as e:
            self.log(f"   no clear answer when guarding instance {iid} ({e}); looking again next pass")
            return
        except vast.Rejected as e:  # unguarded: end it now, rent no replacement yet
            a["ending"] = f"could not schedule its deletion ({e})"
            self.save()
            self.log(f"   ending instance {iid}: {a['ending']}")
            _try(vast.destroy, iid)
            return
        self.save()

    def overdue(self, a: dict, row: dict) -> str | None:
        rec, now = self.rec, time.time()
        if a.get("ending"):
            return a["ending"]
        if rec["state"] != "open" or a["generation"] != rec["generation"]:
            return "finished" if rec["state"] == "done" else "no longer needed"
        if why := vast.failure(row):
            return why
        if not a.get("running") and now > a["claimed"] + STARTUP:
            return "the image did not load in time"
        if now > a["deadline"] + 120:  # the worker should have deleted it itself
            return "deadline passed"
        return None

    def close(self, a: dict) -> None:
        """Vast no longer lists the instance: drop its guards, record why it ended."""
        iid = a["instance"]
        for g in self.p.guards:
            if vast.guard_target(g) == iid:
                vast.remove_guard(g["id"])  # if this fails, the next pass retries
        a["closed"] = time.time()
        a["outcome"] = a.get("ending") or self.worker_outcome(a)
        self.save()
        self.log(f"   instance {iid} is gone: {a['outcome']}")

    def worker_outcome(self, a: dict) -> str:
        """Why the instance went by itself, as far as its worker's log tells
        (written on the host: a diagnosis, not evidence)."""
        try:
            text = (self.vdir / "workers" / f"{a['claim']}.log").read_text(errors="replace")
        except OSError:
            return "vanished"
        if speed := re.search(r"bucket speed (\d+) kB/s", text):
            a["bucket_kBps"] = int(speed[1])
        for needle, outcome in (("all variants uploaded", "worked"),
                                ("GPU unusable", "broken GPU"),
                                ("bucket too slow", "slow bucket link"),
                                ("deadline reached", "deadline passed")):
            if needle in text:
                return outcome
        return "vanished"

    def rent(self) -> None:
        rec, now = self.rec, time.time()
        tries = [a for a in rec["attempts"]
                 if a["generation"] == rec["generation"] and a["create"] != "rejected"]
        if len(tries) >= TRIES:
            self.fail(f"{TRIES} cloud GPUs failed in a row")
            return
        today = time.strftime("%F", time.gmtime(now))
        used = sum(time.strftime("%F", time.gmtime(a["claimed"])) == today
                   for r, _ in self.p.recs for a in r["attempts"] if a["create"] != "rejected")
        if used >= DAILY:
            self.status("Daily rental limit reached; this carries on after midnight UTC, "
                        "at the first visit")
            return
        n = len(tries) + 1
        offer = _offer(fixed=n == TRIES, recs=self.p.recs)
        if offer is None:
            self.status("No cloud GPU within the price limit on offer just now; "
                        "looking again every minute")
            return
        claim = uuid.uuid4().hex[:12]
        a = {"claim": claim, "label": f"{LABEL}{rec['job']}/{claim}",
             "generation": rec["generation"], "try": n,
             "type": "fixed" if n == TRIES else "bid", "claimed": now,
             "deadline": now + ATTEMPT, "create": "claimed", "instance": None,
             **{k: offer[k] for k in ("machine_id", "host_id", "public_ipaddr")},
             "offer": offer["id"], "price": offer["hourly"]}
        rec["attempts"].append(a)
        rec["status"] = ""
        self.save()  # the claim; no rental without it
        self.log(marker(f"renting a cloud GPU (attempt {n} of {TRIES})"))
        self.log(f"   offer {offer['id']} in {offer.get('geolocation')}, "
                 f"${offer['hourly']:.3f}/h, host downloads at {int(offer['inet_down'])} Mbit/s")
        try:
            a["instance"] = vast.create(offer["id"], self.payload(a, offer))
        except vast.Rejected as e:
            a["create"], a["closed"], a["outcome"] = "rejected", time.time(), f"offer refused: {e}"
            self.save()
            self.log(f"   offer refused, trying another: {e}")
            wake()
            return
        except vast.Uncertain as e:
            self.log(f"   no clear answer from Vast ({e}); looking for the rental first")
            self.status(CHECKING)
            return
        a["create"] = "created"
        self.save()
        self.log(marker("loading the transcription software onto the machine"))
        self.guard(a)

    def payload(self, a: dict, offer: dict) -> dict:
        rec = self.rec
        env = {"S3_ACCESS_KEY": os.environ["S3_ACCESS_KEY"],
               "S3_SECRET_KEY": os.environ["S3_SECRET_KEY"],
               "SONG": rec["song"], "VERSION": rec["version"],
               "VARIANTS": " ".join(rec["variants"]), "GENERATION": str(rec["generation"]),
               "RAW_BARS": "1" if rec["raw_bars"] else "0", "CLAIM": a["claim"],
               "SOURCE": f"sources/{rec['job']}/", "DEADLINE": str(int(a["deadline"]))}
        return {"client_id": "me", "image": IMAGE, "disk": 40, "label": a["label"],
                "env": env, "onstart": "bash /app/deploy/vast-worker.sh", "runtype": "ssh",
                "price": offer.get("bid"), "cancel_unavail": True}


def _prepare(vdir: Path, rec: dict) -> None:
    try:
        ingest.prepare(vdir, rec)
    except Exception as e:  # noqa: BLE001 - the coordinator fails the job with it
        _prep_failed[rec["job"]] = str(e) or repr(e)
    wake()


def _offer(fixed: bool, recs: list[tuple[dict, str]]) -> dict | None:
    """A random one of the 5 cheapest suitable offers (cheapest-first kept
    re-renting one broken host) within the price limit, None if none is.
    Bids at BID times the going rate; the fixed price can't be outbid.
    Vast bills the image pull no bandwidth (invoices 2026-10-01: $0 on
    every rental), so only our own transfers count."""
    q: dict = dict(QUERY, type="on-demand" if fixed else "bid")
    machines, sites = _blocklist(recs)
    if machines:
        q["machine_id"] = {"notin": sorted(machines)}
    if sites:
        q["public_ipaddr"] = {"notin": sorted(sites)}
    fit = []
    for o in vast.offers(q):
        bid = None if fixed else round(o["min_bid"] * BID, 4)
        hourly = o["dph_total"] if fixed else o["dph_total"] - o["dph_base"] + bid
        network = TRANSFER_GB * ((o.get("inet_down_cost") or 0) + (o.get("inet_up_cost") or 0))
        if hourly * WORST_HOURS + network <= MAX_HOURLY * WORST_HOURS:
            fit.append(o | {"bid": bid, "hourly": hourly})
    return random.choice(fit[:5]) if fit else None


def _blocklist(recs: list[tuple[dict, str]]) -> tuple[set, set]:
    """Machines, and sites (one address can hold several machines), that
    failed in the past week; the offer search leaves them out."""
    machines, sites = set(), set()
    for rec, _ in recs:
        for a in rec["attempts"]:
            if a.get("closed", 0) < time.time() - 7 * 86400:
                continue
            outcome = a.get("outcome") or ""
            if outcome.startswith(BAD_SITE) and a.get("public_ipaddr"):
                sites.add(a["public_ipaddr"])
            elif outcome.startswith(BAD_MACHINE) and a.get("machine_id"):
                machines.add(a["machine_id"])
    return machines, sites


def _try(call, *args) -> None:
    """A call whose failure the next pass repairs anyway."""
    try:
        call(*args)
    except (vast.Uncertain, vast.Rejected) as e:
        print(f"coordinator: {call.__name__}{args} failed: {e}", flush=True)
