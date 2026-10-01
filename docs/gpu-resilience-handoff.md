# GPU processing resilience — design handoff

Status: problem statement and constraints only. Nothing here is decided or
implemented. The next step is a design: pick the mechanisms, list the open
decisions for the user, then implement in small commits.

Read first: [AGENTS.md](../AGENTS.md), [CLAUDE.md](../CLAUDE.md),
[gpu-workers.md](gpu-workers.md), [operations.md](operations.md) (section
"Cloud test deployment"), [webapp.md](webapp.md) (section "Ingestion jobs"),
and the two GPU items in [roadmap.md](roadmap.md) (bucket test, host record),
which belong to this work.

## Goal

A song submitted with "process on a rented cloud GPU" gets fully processed
even when:

1. nobody keeps the song's page open (phone locked, tab closed);
2. a rented GPU host crashes, stalls, never finishes loading the image, or
   has a broken network route — processing resumes on another host;
3. the cloud web app container sleeps or restarts — on wake-up it continues
   any unfinished processing on any project/version;

while

4. using the Scaleway CPU container for whatever useful work fits while a GPU
   host is still loading;
5. keeping every step idempotent (safe to repeat after a crash);
6. never processing the same thing twice in parallel (no duplicate rentals,
   no two workers on one version).

## What happened on 2026-10-01

One YouTube song (`highway-star/levyversio`) took nearly 3 h and 15 rentals
to process; the GPU work itself took 6 min. Each failure mode below is real.

| time (UTC) | event |
|---|---|
| 12:01 | Created from the phone with the GPU box ticked. Source fetched (yt-dlp), uploaded to the bucket. |
| 12:04 | Last request from the phone — the page stopped polling (screen locked). |
| 12:02–12:17 | Two rentals never got ready (storage-only charges, 12 + 6.5 min). Container CPU throttled the whole time. |
| 12:17 | Third rental created. |
| ~12:19 | Scaleway scaled the idle container to zero — the job thread and `pipeline.log` died with it. The `start` trap that destroys the instance never ran (killed, not exited). |
| 12:21 | Third host ready, nobody to deliver the job. Idle until destroyed by hand at 12:44. |
| 13:01–14:42 | Retries from the laptop: one host stuck retrying image layers for 23 min; three parked as `stopped` (GPU taken); four rentals on 174.164.26.93, whose route to the Scaleway bucket runs at 2–12 KB/s (the worker's `curl` hung forever on the source); one ssh job delivery that died with a silent exit 255 two seconds after a successful GPU check (cause unknown — `LogLevel=ERROR` hides it). |
| 14:42 | Healthy host (92.97.193.95, bucket at 3.4 MB/s). Worker started **detached on the instance** (`nohup setsid`), laptop could sleep. All 3 variants in the bucket by 14:48. |
| ~15:20 | That instance ended up `stopped` (`intended_status=stopped`), **not destroyed** — still billing storage. Either the watchdog's `DELETE` only stops, or the host outbid us just before the watchdog fired. Unverified; destroyed by hand. |

Agent-side mistakes that cost time but are not app problems: the Claude Code
sandbox blocks ssh, and `$TMPDIR` differs inside and outside it.

## How it works today

Flow for a cloud GPU job (`ingest.py`, `deploy/*.sh`):

1. `POST /api/create` → `serve.py` writes `created` and `source-url.txt`,
   copies them to the bucket (`gate.keep`), starts `ingest._job` in a
   **thread inside the web container**.
2. `_fetch`: yt-dlp / gdown / urllib (+ ffmpeg for video). The webapp image
   **does** contain yt-dlp and ffmpeg now (`deploy/Dockerfile`);
   operations.md still says it doesn't — stale.
3. `_run_on_gpu`: uploads the source to `<song>/<version>/source.*`,
   presigns a 24 h URL, runs `deploy/run-on-gpu.sh` as a subprocess.
4. `run-on-gpu.sh` → `gpu-session.sh start` up to 3× (search offers, random
   among 5 cheapest, create with `--ssh --direct` and the watchdog as
   `--onstart-cmd`, wait for ssh up to 90 polls, check
   `torch.cuda.is_available()`), then `gpu-session.sh run`: streams
   `vast-worker.sh` over **one long ssh connection** (`bash -s`), then
   syncs the bucket prefix back into the container's `output/`, then
   destroys the instance (EXIT trap).
5. `vast-worker.sh` on the host: `curl` the source (no timeout), then per
   variant `drum-transcribe run` + `rclone copy` to the bucket + `touch
   /tmp/alive`.
6. Watchdog (instance `onstart`): destroys the instance via the
   per-instance `CONTAINER_API_KEY` once `/tmp/alive` is older than
   `IDLE_MIN` (30). Starts only after the image pull.

Where state lives — almost all of it ephemeral:

| state | where | survives container restart? |
|---|---|---|
| "a job is running" | `ingest.RUNNING` (in-memory set) | no |
| job log, progress markers | `<version>/pipeline.log` in the container | no |
| which instance is ours | `.gpu-instance` in the container CWD | no |
| pinned host key | `.gpu-known-hosts` in the container CWD | no |
| source, results | bucket `<song>/<version>/…` | yes |
| `created`, `source-url.txt` | bucket (via `gate.keep`) | yes |
| what was requested (GPU? which variants?) | nowhere — only in the thread's arguments | no |

Progress (`progress.version_progress`) infers state from the log plus
artifact presence: a variant counts as ready when
`<variant>/sonification.ogg` exists; a log without an end marker and no
thread means "stopped" (shown, never resumed).

Cloud container facts (checked 2026-10-01, `scw container container get`):
`min_scale 0`, `max_scale 1` (one container at most), request timeout
300 s, 1 GB RAM / 500 mvCPU (operations.md). CPU is throttled between
requests, so **background threads only make progress while some request
is in flight** — that is why the page's 1 s polling "keeps the job moving".
Each cold start re-syncs the bucket (`deploy/sync_bucket.py`, ~20 s;
audio files become empty stand-ins, keys under `sources/` skipped).
Scaleway container **triggers support cron schedules**
(`scw container trigger create … cron-config.schedule`), and also SQS/NATS
queues — untested here.

Pipeline caching (`cli.run_pipeline`): stages skip work whose output already
exists (Demucs stems, `beats_raw.json`, …; check each stage before relying
on it). The worker skips the source download if the file exists. Uploads
are per variant with `rclone copy`, which overwrites the same keys. Worker
uploads keep only the Demucs `drums.flac`/`no_drums.flac`; the MDX23C kit
stems (`stems/mdx23c/`) are **not** uploaded, and `fused` needs them — a
resume on a new host after `mdx23c` finished redoes the split (~36 s GPU).

## Failure modes to design for

| # | failure | today | needed |
|---|---|---|---|
| F1 | Orchestrator gone: page closed → container throttled/scaled to zero (also: laptop sleep, agent session ended) | job lost silently; orphaned instance; no log | job must not depend on a live orchestrator connection |
| F2 | Host never finishes the image pull | 22.5 min ssh-wait timeout, longer in practice (90 polls × ~30 s) | earlier give-up; no watchdog runs during the pull |
| F3 | Host parked as `stopped` / outbid before start | handled (2 min) — common: 3 times today | keep |
| F4 | Host with slow route to the bucket | undetected; worker `curl` hangs forever; uploads would crawl | bucket speed check (roadmap); timeouts / low-speed limits on every transfer |
| F5 | ssh delivery drops (exit 255, cause unknown) | job fails; with `run-on-gpu.sh` the instance is destroyed too | job delivery that tolerates a dropped connection; ssh errors visible in the log |
| F6 | Host dies or is outbid mid-job | per-variant uploads survive; nothing resumes | detect (heartbeat), re-rent, continue with the missing variants |
| F7 | Instance ends `stopped`/`exited` instead of destroyed | storage bills indefinitely, nobody notices | verify the watchdog's `DELETE`; a sweeper that destroys stopped/exited instances |
| F8 | Stall inside a variant (`/tmp/alive` only touched per variant) | watchdog waits the full idle time; a long variant could trip it | heartbeat independent of stage boundaries, plus per-step timeouts so a stall becomes a failure |
| F9 | Wait loop doesn't notice a destroyed instance (`vast show instance` keeps answering with `actual_status` null → logged as "starting"; `alive()` greps for the key and likely reports it alive) | loop runs to its timeout | treat null/missing status as gone |
| F10 | Two launchers for one version (laptop `run-on-gpu.sh` and the cloud app; or a second wake-up) | nothing prevents it | one shared lease per version |

## The six requirements — gaps and options

These are options to evaluate, not decisions.

### 1. No dependence on an open page

The container cannot be the thing that waits: its CPU is throttled without
requests, and it scales to zero. Two directions, combinable:

- **Autonomous worker.** The instance runs the job itself: started from
  `--onstart-cmd` (runs after the image pull, so the container doesn't have
  to wait for ssh at all) or delivered over a short ssh call and detached
  (`nohup setsid … < /dev/null &` — what worked today). The worker reads
  its job spec, writes a heartbeat and progress to the bucket, uploads per
  variant, and destroys its own instance when done or when its own health
  checks fail (GPU, bucket speed). The container only creates the rental
  (seconds) and later reads the bucket. Caveat: with `--onstart-cmd`, the
  job's S3 credentials go into `--env` and are visible in the Vast console
  and to the host — the same exposure as today's ssh stream, but check.
- **Periodic wake-up.** A Scaleway cron trigger calls a reconcile endpoint
  (e.g. every few minutes while jobs are open). Each call is a request, so
  the container gets CPU for up to 300 s. Cost: each wake-up is a cold
  start (~23 s) plus bucket sync, unless the container is still warm.
  Needs a way to switch the trigger off, or a cheap no-op, when nothing is
  pending. Alternatives: Scaleway Serverless Jobs (run-to-completion) or
  the SQS/NATS triggers — unverified.

The page's progress view would then read the bucket's job state instead of
the in-memory thread.

### 2. Resume on a new host

Needs: a liveness signal (heartbeat object with a timestamp, written by a
loop in the worker independent of stages); a reconciler that sees a stale
heartbeat or a dead/stopped instance and re-rents; resume at variant
granularity (already natural: skip variants whose outputs are complete in
the bucket); caps — attempts per version, spend per version/day — so a
broken offer pool can't burn money in a loop; the host record and bucket
test from the roadmap, so a re-rent avoids known-bad hosts (block by IP:
two offers today were the same site).

Stalls have to turn into failures to be resumable: `curl
--speed-limit/--speed-time`, rclone `--timeout`/`--contimeout`, an overall
per-variant time budget.

Decide whether to upload `stems/mdx23c/` so `fused` can resume without
redoing the split, or accept the ~36 s.

### 3. Continue unfinished work on wake-up

Today "unfinished" can't be told apart from "deliberately partial": e.g.
`the-police-nothing-achieving/hd` has only `beats.json`; old versions have
no record of whether GPU processing was requested. So inferring work from
missing files is unsafe — it would rent GPUs for legacy versions.

Likely needs an explicit, durable **job record** per version in the bucket
(requested variants, GPU or not, attempt count, state, timestamps, current
instance id / lease). Reconcile = list job records that are open, skip those
with a live lease, launch the rest within the caps.

Wake-ups also come from scanners and bots (see the roadmap item on probe
paths), so reconcile-on-start must be cheap and cap-guarded — a bot must
not be able to trigger rentals beyond what the open jobs justify.

### 4. CPU work while the GPU host loads

Time budget on a GPU run: image pull 1–10 min (up to 23+ when broken), GPU
compute ~3 min for a 4.6 min song, uploads 2–8 min depending on the host's
route (most bytes are the two Demucs FLACs, ~70 MB each).

Facts that limit the options:

- The container only computes while a request is in flight (see 1), and
  each request may last at most 300 s. Long CPU work there needs a page
  open, a cron wake-up, or a different Scaleway product.
- The webapp image has no torch/ML stack on purpose (small image, fast
  cold start). beat_this, Demucs, ADTOF, MDX23C all need torch.
- 1 GB RAM, 0.5 vCPU.

Candidates to evaluate:

- Fetching the source (yt-dlp, ffmpeg) and uploading it **in parallel
  with** renting, instead of before — the rental doesn't need the source
  until the worker starts. Probably the cheapest win.
- Post-processing that needs no torch: quantize → MusicXML → audition MIDI
  could run in the container from `onsets.json` + `beats.json`. Check each
  module's imports. Sonification needs audio decode/encode; `.mscz` export
  needs MuseScore (only in the GPU image).
- Beat tracking on CPU in the container: needs torch — likely a no.
- Shrinking uploads (e.g. Opus instead of FLAC for the playback stems)
  would shorten the GPU rental on slow-route hosts more than any CPU
  offload. Quality trade-off is the user's call.

### 5. Idempotency

Every step must be safe to repeat after a crash at any point:

- Pipeline stages: cached by output existence — verify per stage, and that
  a crash mid-write can't leave a truncated output that later counts as
  done (write to a temp name, rename).
- Bucket: one object PUT is atomic; a variant's file set is not, and rclone
  copy order is not defined. `progress` treats `sonification.ogg` as
  "variant ready", so a half-uploaded variant can look done. Needs a
  completion marker written last (or an upload order that guarantees it).
- Renting is **not** idempotent: every `create instance` is a new rental.
  Guard it with the lease (requirement 6), and label instances
  (`vastai create … --label <song>/<version>`) so a fresh container can
  find live ones with `vastai show instances`.
- Presigned URLs expire (24 h); regenerate instead of storing.

### 6. No duplicate processing

- One lease per version in the bucket (owner, instance id, expiry,
  heartbeat). With `max_scale 1` there is normally one container, but
  during a redeploy two can overlap, and the laptop scripts act on the
  same bucket — so the lease needs compare-and-set semantics. Check
  whether Scaleway Object Storage supports conditional writes
  (`If-None-Match`/`If-Match` on PUT); if not, design for a single
  writer and make the laptop path go through the same lease.
- The bucket is untrusted (gpu-workers.md §3): every rented host holds the
  worker key and can write any key, including other versions' job records
  and leases. Whatever the reconciler reads from the bucket — instance ids,
  states, timestamps — is attacker-controlled input. Never destroy or
  trust an instance id without checking it against `vastai show instances`
  for our own account and label.

## Cross-cutting

- **Persistent logs.** `pipeline.log` should reach the bucket (worker
  appends its own log; container appends its lines), so a failure is
  explainable after a restart. Today's first failure left no trace.
- **Cost guardrails.** Attempt and spend caps; a sweeper for
  stopped/exited instances (F7); the watchdog must cover the pull phase
  (F2) — today a host stuck pulling is guarded only by the caller's wait
  loop, which is exactly what disappears in F1.
- **User-facing state.** The musician user reads the page: show "trying
  another machine (attempt 2 of 3)" rather than a frozen progress bar;
  explain in README/webapp docs what happens if they close the page.
- **Docs to fix along the way:** operations.md (yt-dlp/ffmpeg are in the
  image; the "keep the page open" caveat), gpu-workers.md (watchdog
  "destroys" — verify F7; detached delivery).

## Open decisions for the user

- Spend caps: max attempts per song, max € per song/day.
- Is a periodic cron wake-up acceptable (small standing cost while jobs are
  open), or must everything be driven from the GPU side?
- Opus vs FLAC for the uploaded playback stems.
- Keep `run-on-gpu.sh` from the laptop as a first-class path, or make the
  laptop just another client of the same job records?

## Verifying a design

Fault injection on real rentals (a few cents each): close the page right
after submitting; destroy the instance mid-pull and mid-variant; kill the
worker; block the bucket on the host (`iptables` drop to
s3.fr-par.scw.cloud) to simulate F4; redeploy the container mid-job; submit
the same version from laptop and cloud at once; let a job finish and check
the instance is gone (not stopped) in `vastai show instances` and
`vastai show invoices`.
