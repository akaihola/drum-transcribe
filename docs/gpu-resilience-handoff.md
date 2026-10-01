# GPU processing resilience — design handoff

Status (2026-10-01): problem statement, the user's decisions, research
results and a proposed design. Nothing is implemented. Next step: run the
two cheap tests under "Still to test", then implement the design in the
order given, in small commits.

Read first: [AGENTS.md](../AGENTS.md), [CLAUDE.md](../CLAUDE.md),
[gpu-workers.md](gpu-workers.md), [operations.md](operations.md) (section
"Cloud test deployment"), [webapp.md](webapp.md) (section "Ingestion jobs"),
the research behind this doc,
[gpu-resilience-research.md](gpu-resilience-research.md) (cited below as
A = Scaleway, B = Vast.ai, C = code, e.g. "B §2"), and the two GPU items in
[roadmap.md](roadmap.md) (bucket test, host record), which belong to this
work.

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

Goal 1 is limited by a decision below: with no periodic wake-ups, work
continues while the container is up and otherwise on the next visit.

## What happened on 2026-10-01

One YouTube song (`highway-star/levyversio`) took nearly 3 h and 15 rentals
to process; the GPU work itself took 6 min. Each failure mode below is real.

| time (UTC) | event |
|---|---|
| 12:01 | Created from the phone with the GPU box ticked. Source fetched (yt-dlp), uploaded to the bucket. |
| 12:04 | Last request from the phone (12:04:52) — the page stopped polling (screen locked). |
| 12:02–12:17 | Two rentals never got ready (storage-only charges, 12 + 6.5 min). |
| 12:17 | Third rental created — by the job thread, 12.5 min after the last request, so threads do get some CPU without a request in flight (A §3). |
| 12:20–12:22 | Scaleway scaled the idle container to zero (15–17 min after the last request, A §3) — the job thread and `pipeline.log` died with it. The `start` trap that destroys the instance never ran (killed, not exited). |
| 12:21 | Third host ready, nobody to deliver the job. Idle until destroyed by hand at 12:44. |
| 13:01–14:42 | Retries from the laptop: one host stuck retrying image layers for 23 min; three parked as `stopped` (GPU taken); four rentals on 174.164.26.93, whose route to the Scaleway bucket runs at 2–12 KB/s (the worker's `curl` hung forever on the source); one ssh job delivery that died with a silent exit 255 two seconds after a successful GPU check (cause unknown — `LogLevel=ERROR` hides it). |
| 14:42 | Healthy host (92.97.193.95, bucket at 3.4 MB/s). Worker started **detached on the instance** (`nohup setsid`), laptop could sleep. All 3 variants in the bucket by 14:48. |
| ~15:20 | That instance ended up `stopped`, not destroyed, still billing storage. Vast stopped it itself at ≈15:18–15:23, most likely outbid: the account audit log has no DELETE or stop call before our manual destroy at 15:28:52. The watchdog's DELETE does destroy (verified 2026-09-20), but it was due at 15:18–15:19 and made no call; why is unknown (B §1). |

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
   `IDLE_MIN` (30). Starts only after the image pull, and dies with the
   container when Vast stops the instance.

Where state lives — almost all of it ephemeral (C §6 lists every touch
point):

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

Cloud container facts (A §3): `min_scale 0`, `max_scale 1` (one container
at most), request timeout 300 s (settable up to 60 min), 1 GB RAM /
500 mvCPU. It scales to zero 15–17 min after the last request and is
billed per second of uptime, idle tail included: each cold wake costs
≈16.5 min ≈ €0.007, always-on would be ≈ €18/month, and other containers
already use most of the account's free tier. How much CPU a thread gets
with no request in flight is undocumented — the 12:17 rental shows it is
not zero (test T1). Each cold start re-syncs the bucket
(`deploy/sync_bucket.py`, median 17 s; audio files become empty
stand-ins, keys under `sources/` skipped).

Pipeline caching (`cli.run_pipeline`, C §1): every stage skips when its
output file exists, and no write is atomic, so a crash can leave a
truncated file that later counts as done: the worker's source download,
Demucs `no_drums.flac`, `beats_raw.json`, `onsets.json`. Uploads are per
variant with `rclone copy` (parallel, no defined order). Worker uploads
keep only the Demucs `drums.flac`/`no_drums.flac` (~88 % of the bytes);
the MDX23C kit stems (`stems/mdx23c/`) are **not** uploaded, and `fused`
needs them — a resume on a new host after `mdx23c` finished redoes the
split (~36 s GPU).

## Failure modes to design for

| # | failure | today | needed |
|---|---|---|---|
| F1 | Orchestrator gone: page closed → container scaled to zero (also: laptop sleep, agent session ended) | job lost silently; orphaned instance; no log | job must not depend on a live orchestrator connection |
| F2 | Host never finishes the image pull | 22.5 min ssh-wait timeout, longer in practice (90 polls × ~30 s); Vast has no server-side time limit and no pull progress (B §5) | earlier give-up; no watchdog runs during the pull |
| F3 | Host parked as `stopped` / outbid before start | handled (2 min) — common: 3 times today | `--cancel-unavail` refuses such a bid at once, no charge (B §5); fixed price on the last try |
| F4 | Host with slow route to the bucket | undetected; worker `curl` hangs forever; uploads would crawl. The host's advertised `inet_up` doesn't predict it (B §6) | bucket speed check (roadmap); low-speed limits on every transfer |
| F5 | ssh delivery drops (exit 255, cause unknown) | job fails; with `run-on-gpu.sh` the instance is destroyed too | no ssh (design §2) |
| F6 | Host dies or is outbid mid-job | per-variant uploads survive; nothing resumes | detect, re-rent, continue with the missing variants |
| F7 | Instance ends `stopped`/`exited` instead of destroyed | the watchdog's DELETE does destroy, but a Vast-side stop kills the watchdog with the container; storage bills until someone notices | sweeper destroys our labelled instances that are stopped/exited/unknown/offline |
| F8 | Stall inside a variant (`/tmp/alive` only touched per variant) | watchdog waits the full idle time; a long variant could trip it | low-speed limits plus an overall time budget, so a stall becomes a failure |
| F9 | Wait loop misreads Vast: a destroyed instance answers `{"instances": null}`, logged as "starting"; an API error (empty stdout, CLI still exits 0) is logged as "instance disappeared". `alive()` handles destroyed correctly but counts stopped as alive (B §2) | loop runs to its timeout | the status rule in B §2 |
| F10 | Two launchers for one version (laptop `run-on-gpu.sh` and the cloud app; a second wake-up; a meter switch during a job — `_rerun` ignores `RUNNING`, C §5) | nothing prevents it | one lease per version |

## Decisions (2026-10-01, with the user)

| question | decision |
|---|---|
| Spend caps | 5 rentals per version, then the page says it failed and offers a retry. Across all songs about €1/day, counted as rentals (30/day; a rental costs ≤ 3 ¢ when the guards work). |
| Who drives the work when nobody watches | **No periodic wake-ups** (no cron trigger, no Serverless Job). The container works while it is up — while a page is open, plus the 15–17 min it stays up afterwards — and continues on the next visit. Accepted: a host stuck loading, or bumped mid-job, bills storage (≈0.2–2.5 ¢/h) until then. |
| Rental type | Bid on tries 1–4 (1.25× the floor, `--cancel-unavail`); fixed price (on-demand, never outbid; ≈ +1–1.5 ¢ per song) on try 5. |
| Playback stems | Upload the Demucs drums / without-drums tracks as Opus (`.ogg`, sonify's setting, ≈ 7× smaller), not FLAC. The page's download becomes Opus; the user doesn't need FLAC there. FLAC stays only on the GPU host. |
| Laptop path | Only the web app rents. The laptop submits through the web form and pulls results with `rclone sync`. `run-on-gpu.sh` and the `gpu-session.sh` keep-alive session go away; the manual `vastai` steps in gpu-workers.md §4 stay for debugging. |

## Design (proposed)

Agent-side choices that follow from the decisions and the research; no
further user input needed. Numbered in implementation order.

### 1. Worker: stalls become failures, every step repeatable

- Transfers: `curl --speed-limit/--speed-time` and `-o "$src.part" && mv`;
  rclone `--timeout`, `--contimeout` and a low-speed cutoff. Timing the
  source download doubles as the bucket speed test (roadmap): below a
  threshold the worker gives up on the host.
- The GPU check moves into the worker.
- Atomic local writes (C §1): one temp-file + `os.replace` helper for
  `BeatGrid.save`, `save_onsets`, `save_events`; unparsable cache files
  count as missing (also keeps one bad file from breaking `/api/index`);
  Demucs skips only when a marker written after both stems exists.
- Completion marker: after `rclone copy` of a variant succeeds, upload
  `<variant>/done`. The adtof marker also covers the shared files (source,
  stems, beats).
- Opus: the worker encodes `drums`/`no_drums` to `.ogg` for upload; the
  FLACs are never uploaded. `separate_drums` runs only when onsets or kit
  stems are missing (today it runs every time, `cli.py:121`), so synced
  results don't make the laptop redo Demucs. Page and progress accept both
  names, so old FLAC versions keep working (readers listed in C §4).
- The worker uploads its own log, `<song>/<version>/worker.log`, every
  60 s; its modification time is the heartbeat.
- Don't upload `stems/mdx23c/`: more upload time than the ~36 s split it
  saves.

### 2. Delivery without ssh

- `--onstart-cmd` carries everything: the worker inline as gzip+base64
  (onstart is limited to 4048 characters; the worker is 1.7 KB compressed
  today — if it outgrows that, bake it into the image), run as
  `timeout <budget> bash worker.sh`, then destroy the own instance with
  `CONTAINER_API_KEY` and log the DELETE's HTTP status to the bucket
  (B §1 left the 10-01 silence unexplained). Success destroys at once — no
  idle wait, so the window in which an outbid can strand a host is the job
  itself.
- Job spec (`SONG`, `VERSION`, `VARIANTS`, presigned `SOURCE_URL`) and the
  worker S3 key go in `--env` — visible to the host and in `show
  instance`, the same exposure as today's ssh stream (B §4).
- `--label <song>/<version>` on every rental (B §3).
- Onstart re-runs when an outbid instance resumes; the worker then skips
  variants that have `done` markers and finishes.
- Removed: ssh delivery (F5), `GPU_SSH_KEY_B64`, host-key pinning,
  `openssh-client` in the image, the idle watchdog loop, `.gpu-instance`.

### 3. Trusted job state

Every rented host holds the worker key, so anything in the results bucket
is untrusted. Bucket policies are allow-only and can't exclude a prefix
(A §2), so job state gets its own bucket:

- New bucket `drum-transcribe-jobs`, new IAM application with a key for the
  container only; the bucket policy lists that application and the user's
  `user_id` (anyone not listed is locked out, which shuts out the worker
  key). The container gets the key as a seventh secret — remember that
  `secret-environment-variables` updates replace the whole map.
- Per version, `<song>/<version>.json`: requested variants, attempts (with
  rental type), state (open/done/failed), current instance id, timestamps.
  Written with conditional PUTs (`If-None-Match: *` to create, `If-Match:
  <etag>` to update; verified on Scaleway, A §1), so the record is the
  lease (F10). The meter rerun takes the same lease.
- The container's own log for the version, `<song>/<version>.log`, the
  daily rental counter, and the host record (design §6) live here too.

### 4. Reconcile

One cheap, idempotent function. Runs at container start, on page requests
(at most once a minute), and in a loop thread while the container is up
(worth it if T1 shows CPU without requests). For each open job record:

- Ask Vast `show instances --label <song>/<version>`. Only ids from that
  answer are ever destroyed — never ids read from a bucket.
- All requested `<variant>/done` present → sync results, mark done.
- A live instance: leave it if `running` with a fresh heartbeat; destroy it
  and count the attempt if it is dead by the B §2 status rule, `loading`
  longer than `45 s + 6 × 8 GB / inet_down` plus a margin (F2), or its
  heartbeat is stale.
- No live instance: rent if attempts < 5 and the daily cap allows (try 5 at
  fixed price); otherwise mark failed.

Sweeper in the same pass: destroy any labelled instance that is
stopped/exited/unknown/offline (F7), with or without a record. Vast status
rule (B §2): empty stdout or `"error": true` on stderr means an API problem,
retry (the CLI exits 0 either way); `{"instances": null}` means gone.

### 5. Submission

`/api/create` writes the job record, rents (seconds), and fetches and
uploads the source in parallel with the image pull — the only useful CPU
work for the container (requirement 4; no pipeline stage is worth moving
there, C §3). The worker waits a bounded time for the source object. The
presigned URL is made per rental.

### 6. Host record and blocklist

The roadmap item, kept in the jobs bucket: one line per rental (machine_id,
host_id, public_ipaddr, outcome, pull time, bucket speed). The offer query
excludes recent failures: `public_ipaddr notin [...]` for slow routes,
`machine_id notin [...]` for broken boxes (both filter on the server,
B §6).

### 7. Page and docs

Versions with a job record read state from it plus the `done` markers and
`worker.log`; old versions keep the `sonification.ogg` rule. Show "trying
another machine (attempt 2 of 5)" and "failed — try again". Explain in
README/webapp.md what happens when the page is closed. Fix operations.md
(yt-dlp/ffmpeg are in the image; "keep the page open") and gpu-workers.md
(onstart delivery; the claim that `CONTAINER_API_KEY` reaches "only that
one instance" is undocumented, B §1).

### Not doing

- Cron triggers, Serverless Jobs, queue delays: ruled out by the wake-up
  decision; Scaleway queues can't delay messages anyway (A §4–6).
- Vast webhooks (outbid/stopped/error events, B §5): would wake the
  container only when something breaks, but need a key or setting made in
  the Vast console. Revisit if stranded hosts cost more than expected.

## Cross-cutting

- **Narrow the worker key first** (independent of the rest): it has
  `ObjectStorageFullAccess` on the whole Scaleway project, so any rented
  host can change the results bucket's CORS, versioning or lifecycle — a
  lifecycle rule could expire every object (A §2).
  `ObjectStorageObjectsRead/Write/Delete` is enough for the worker.
- **Cost guardrails**: attempt and daily caps (decisions), the sweeper
  (F7), `--cancel-unavail` (F3). Storage bills from creation, during the
  pull too, and for up to ~5 min after a destroy (B §7).

## Still to test

Cheap, before or during implementation:

- **T1 — CPU without a request.** A probe endpoint starts a thread that
  logs a busy-loop counter every 10 s; compare rates during and after the
  request in Cockpit. Decides whether the reconcile loop thread is worth
  having.
- **T2 — one test rental** (a few cents): the watchdog-style DELETE on the
  current image, with its HTTP status logged; what `CONTAINER_API_KEY` can
  reach (`GET /instances/`, `/users/current/` from inside); `--cancel-unavail`
  on a bid; a label containing `/`; a ~4 KB `--env` value; and whether a
  Vast scheduled job (`/commands/schedule_job/`, B §5) accepts `DELETE
  /instances/<id>/`. If it does, it is a server-side backstop for a host
  stuck loading — the one gap the wake-up decision leaves.

## Verifying the implementation

Fault injection on real rentals (a few cents each): close the page right
after submitting; destroy the instance mid-pull and mid-variant; kill the
worker; block the bucket on the host (`iptables` drop to
s3.fr-par.scw.cloud) to simulate F4; redeploy the container mid-job;
submit the same version twice at once and switch the meter during a job;
let a job finish and check the instance is gone (not stopped) in `vastai
show instances` and `vastai show invoices`.
