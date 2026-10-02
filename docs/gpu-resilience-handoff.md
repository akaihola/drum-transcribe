# GPU processing resilience — design handoff

Status (2026-10-02): design reviewed and revisions approved by the user.
The 2026-10-01 research and tests remain the evidence; the revised design
is not implemented. Follow the [Honey principles](https://raw.githubusercontent.com/Green-PT/honey-for-devs/refs/heads/main/skills/honey/SKILL.md):
reuse the worker already in the image, keep one rental coordinator, and
make crash recovery explicit. Implement in the order below, in small commits.

Read first: [AGENTS.md](../AGENTS.md), [CLAUDE.md](../CLAUDE.md),
[gpu-workers.md](gpu-workers.md), [operations.md](operations.md) (section
"Cloud test deployment"), [webapp.md](webapp.md) (section "Fetching a new version"),
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
There is also a crash window between creating a rental and installing its
scheduled DELETE. Without a completed schedule, cleanup waits for the next
visit. Conditional bucket writes cannot make those Vast calls atomic.
If a creation outcome cannot be established, processing waits for account
or audit-log inspection rather than risking a duplicate rental.

## What happened on 2026-10-01

One YouTube song (`highway-star/levyversio`) took nearly 3 h and 15 rentals
to process; the GPU work itself took 6 min. Each failure mode below is real.

| time (UTC) | event |
|---|---|
| 12:01 | Created from the phone with the GPU box ticked. Source fetched (yt-dlp), uploaded to the bucket. |
| 12:04 | Last request from the phone (12:04:52) — the page stopped polling (screen locked). |
| 12:02–12:17 | Two rentals never got ready (storage-only charges, 12 + 6.5 min). |
| 12:17 | Third rental created — by the job thread, 12.5 min after the last request: threads get full CPU without a request in flight (test T1). |
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
   contains yt-dlp and ffmpeg (`deploy/Dockerfile`), not gdown.
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
already use most of the account's free tier. A background thread gets
full CPU the whole time, with or without a request in flight (test T1).
Each cold start re-syncs the bucket
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
| F2 | Host never finishes the image pull | 22.5 min ssh-wait timeout, longer in practice (90 polls × ~30 s); no pull progress in the API (B §5) | earlier give-up; no watchdog runs during the pull, but a Vast scheduled DELETE does (test T2) |
| F3 | Host parked as `stopped` / outbid before start | handled (2 min) — common: 3 times today | `--cancel-unavail` refuses such a bid at once, no charge (B §5); fixed price on the last try |
| F4 | Host with slow route to the bucket | undetected; worker `curl` hangs forever; uploads would crawl. The host's advertised `inet_up` doesn't predict it (B §6) | bucket speed check (roadmap); bounded transfers |
| F5 | ssh delivery drops (exit 255, cause unknown) | job fails; with `run-on-gpu.sh` the instance is destroyed too | no ssh (design §3) |
| F6 | Host dies or is outbid mid-job | per-variant uploads survive; nothing resumes | detect, re-rent, continue with the missing variants |
| F7 | Instance ends `stopped`/`exited` instead of destroyed | the watchdog's DELETE does destroy, but a Vast-side stop kills the watchdog with the container; storage bills until someone notices | sweeper destroys our labelled instances that are stopped/exited/unknown/offline |
| F8 | Stall inside a variant (`/tmp/alive` only touched per variant) | watchdog waits the full idle time; a long variant could trip it | explicit attempt deadline; a quiet log alone does not mean failure |
| F9 | Wait loop misreads Vast: a destroyed instance answers `{"instances": null}`, logged as "starting"; an API error (empty stdout, CLI still exits 0) is logged as "instance disappeared". `alive()` handles destroyed correctly but counts stopped as alive (B §2) | loop runs to its timeout | the status rule in B §2 |
| F10 | Two launchers for one version (laptop `run-on-gpu.sh` and the cloud app; a second wake-up; a meter switch during a job — `_rerun` ignores `RUNNING`, C §5) | nothing prevents it | one coordinator; persist an attempt claim before renting; reject meter changes during processing |

## Decisions (2026-10-01, clarified in the approved 2026-10-02 review)

| question | decision |
|---|---|
| Spend caps | 5 rentals per version before an explicit retry. Across all songs about €1/day, counted as rentals (30/day). The intended cost is at most about 3 ¢ per rental; this is a target to verify against price limits and actual scheduled deletion times, not a demonstrated ceiling. |
| Who drives the work when nobody watches | **No periodic wake-ups** (no cron trigger, no Serverless Job). The container works while it is up, including the ~17 min after the last request with full CPU (T1), and continues on the next visit. Accepted: a host without a working deletion schedule can bill storage until then. A scheduled DELETE runs without the container, including during an image pull (design §3). |
| Rental type | Bid on tries 1–4 (1.25× the floor, `--cancel-unavail`); fixed price (on-demand, never outbid; ≈ +1–1.5 ¢ per song) on try 5. |
| Playback stems | Upload the Demucs drums / without-drums tracks as Opus (`.ogg`, sonify's setting, ≈ 7× smaller), not FLAC. The page's download becomes Opus; the user doesn't need FLAC there. FLAC stays only on the GPU host. |
| Laptop path | Only the web app rents. The laptop submits through the web form and pulls results with `rclone sync`. `run-on-gpu.sh` and the `gpu-session.sh` keep-alive session go away; the manual `vastai` steps in gpu-workers.md §4 stay for debugging. |

## Design (approved, not implemented)

These choices follow from the approved review, decisions and research.
Numbered in implementation order.

### 1. Trusted job state and rental claims

Every rented host holds the worker key, so anything in the results bucket
is untrusted. Bucket policies are allow-only and can't exclude a prefix
(A §2), so job state gets its own bucket:

- New bucket `drum-transcribe-jobs`, new IAM application with a key for the
  container only; the bucket policy lists that application and the user's
  `user_id` (anyone not listed is locked out, which shuts out the worker
  key). The container gets the key as a seventh secret — remember that
  `secret-environment-variables` updates replace the whole map.
- Per version, `<song>/<version>.json` holds a stable job id, original
  source URL or uploaded input key, source preparation state, requested
  variants, the raw-bar setting, a result generation number, job state
  (`open`/`done`/`failed`), attempts, and pending cleanup.
- Each attempt holds its unique claim id and label, generation, rental
  type, timestamps and deadlines, instance id, schedule id and outcome.
  Host measurements belong in this record too (design §6).
- Create and update synchronously with conditional PUTs (`If-None-Match:
  *`, `If-Match: <etag>`; A §1). Do not use `gate.keep`'s fire-and-forget
  upload for authoritative job state. A failed write means no rental.
- Before calling Vast, persist an attempt claim and reserve its count
  against the five-rental allowance and 30-rental UTC-day cap. Derive the
  daily total from dated attempts across jobs; the single coordinator is
  the only writer of rental reservations. Count uncertain creations
  conservatively; release a reservation only on a definite rejection
  that created no rental. Do not count the same attempt again on failure.
- A claim with an uncertain create result stays unresolved. Recover its
  instance by its unique label before doing anything else; never repeat
  the create call or launch a replacement while the outcome is unknown.
  A crash before sending the call can be indistinguishable from a lost
  response. If listing cannot resolve it, inspect the account/audit log;
  do not expire the claim into a retry. Conditional writes protect the
  record, not the external Vast call.
- Explicit retry starts a new generation and five-rental allowance;
  retain the attempt history and daily counts. Rerunning a completed
  version after a meter change also starts a generation. A `done` marker
  is valid only for the generation stored in the trusted job record.
- The container's own version log, `<song>/<version>.log`, lives here too.
  Result completion and rental cleanup are separate fields; `done` or
  `failed` jobs with pending cleanup remain the coordinator's responsibility.

### 2. Worker: bounded work and repeatable steps

- Use `/app/deploy/vast-worker.sh`, already copied into the GPU image by
  `Dockerfile.gpu`. Update and rebuild that image with worker changes;
  no gzip/base64 delivery or script-size fallback.
- Move the GPU check into the worker. On a replacement host, download
  the original source and restore the shared `beats_raw.json` and cached
  `onsets.json` files before continuing. Validate JSON caches, apply the
  job's raw-bar setting, and skip only variants whose remote `done`
  markers match the requested generation. Downloads must be real audio,
  not the web container's zero-byte stand-ins.
- Transfers use explicit connection, idle and total time limits. For
  HTTP downloads use `curl --speed-limit/--speed-time` and a total timeout,
  writing to a `.part` file before renaming. For rclone use `--contimeout`,
  `--timeout` and `--max-duration`; `--timeout` alone measures inactivity,
  not slow throughput ([rclone docs](https://rclone.org/docs/#max-duration-duration)).
  The timed source download is the bucket speed test (roadmap); reject a
  slow host before starting the pipeline. Waiting for a source that has
  not been uploaded yet is separate from timing its transfer.
- Atomic local writes (C §1): one temp-file + `os.replace` helper for
  `BeatGrid.save`, `save_onsets`, `save_events`; invalid caches count as
  missing, including in `/api/index`. Demucs skips only when both stems
  and a marker written after their successful creation exist.
- Upload the generated shared files and current variant, then write
  `<variant>/done` containing the generation number. The first completed
  variant covers the shared source, playback stems and beat grid, whether
  or not it is adtof. Exclude completion markers and user feedback from
  bulk copies; they must not be overwritten by restored files.
- Encode `drums`/`no_drums` as Opus `.ogg` for playback upload. Keep FLACs
  and `stems/mdx23c/` on the host only. Call `separate_drums` only when
  missing onsets require it; cached onsets do not require kit stems.
  A replacement host recomputes Demucs and the kit split when needed.
  Page and progress accept both `.ogg` and old `.flac` names (C §4).
- Upload a log per attempt, `<song>/<version>/workers/<claim-id>.log`,
  every 60 s and at exit, with bounded, best-effort transfers. Logs show
  progress; their modification time is not a liveness test. A quiet
  inference stage or unchanged log must not trigger another rental.

### 3. Delivery and deletion without ssh

- A short `--onstart-cmd` invokes the worker already in the image. Pass
  `SONG`, `VERSION`, `VARIANTS`, generation, raw-bar setting, claim id,
  source input prefix and the absolute attempt deadline in `--env`, along
  with the worker S3 key. That key already lets the worker fetch inputs;
  no separate presigned source URL is needed. Env values remain visible
  to the host and in `show instance`, as today (B §4).
- Label every rental `drum-transcribe/<job-id>/<claim-id>` (B §3). Persist
  this label before creation. Only this namespace belongs to the automatic
  sweeper; manual rentals with other labels are left alone.
- Bound the worker by the remaining time until the persisted attempt
  deadline, including source waiting and uploads. Do not reset the budget
  on an instance resume. On success, failure or timeout, attempt its own
  DELETE with `CONTAINER_API_KEY`. Use bounded cleanup that runs on error
  too; record the HTTP status in the attempt log if possible. Self-deletion
  can kill logging, so absence in Vast is the authoritative confirmation.
- Immediately after creation, schedule a Vast
  `DELETE /api/v0/instances/<id>/` (`POST /commands/schedule_job/`, T2).
  Persist the schedule id and actual deletion time. On wake-up, adopt any
  rental whose id was not saved, inspect its schedules and install a
  missing guard. A failed scheduling call triggers destruction, not
  another rental. An uncertain scheduling result must be recovered by
  inspecting schedules; any duplicate deletion guards are cleaned up
  after the instance is confirmed gone.
- Scheduling and creation are separate calls. A container crash between
  them leaves an unguarded rental until the next visit. This cannot be
  eliminated by conditional S3 writes or a local `finally` block.
- T2 proved hourly scheduled deletion, not an arbitrary minute deadline.
  Verify `min_of_the_hour` and `start_time` before choosing numeric startup,
  attempt and transfer limits. If only full-hour deletion is available,
  budget for that actual delay and reject offers above the resulting price
  ceiling. The three-cent target needs this check, including GPU, disk and
  network charges; 30 rentals alone is not a strict euro cap.
- Keep the schedule until Vast confirms the instance is gone, then delete
  it and clear pending cleanup. Result markers or a successful DELETE
  response alone do not allow removal of the guard.
- Removed: ssh delivery (F5), `GPU_SSH_KEY_B64`, host-key pinning,
  `openssh-client` in the web image, the idle watchdog and `.gpu-instance`.

### 4. Reconcile

One coordinator thread runs reconciliation at startup and at most once a
minute while the container is up. Requests wake that thread; they never
call reconciliation or rent directly. Source fetching can run alongside
it, but rental claims, accounting and cleanup have one owner. T1 showed
that the thread works for the ~17 min after the last request too.

`honey: one coordinator process with max_scale 1; add ownership fencing
before increasing scale or allowing overlapping deployments.`

Each pass reads trusted job records and asks Vast for the account's
instances once, matching our labels locally. Only ids confirmed in that
answer can be destroyed; ids from result files are never instructions.

- Recover unresolved creation claims and missing schedules first. API
  errors leave state uncertain; do not interpret them as permission to rent.
- Resume interrupted source preparation from its durable URL or upload
  (design §5). A definite source error fails the job and cleans up its
  rental, without spending the remaining allowance on the same bad input.
- Sync completed variants as they arrive. All requested generation-matched
  markers present means processing is done, but cleanup continues. Destroy
  any remaining rental and remove its schedule only after confirmed absence.
- For a live open job, destroy on a failed Vast status, an explicit startup
  deadline while provisioning/loading, or the overall attempt deadline.
  Use fixed limits validated in §3; host download speed is diagnostic,
  not a second timeout formula. A stale or missing log is diagnostic too.
- Confirm the previous rental is gone before creating a replacement.
  Reserve its attempt first; tries 1–4 are bids, try 5 fixed price. Five
  rentals fail the generation and offer a retry after cleanup. The daily
  cap leaves work open, with a message; it resumes on a visit after the
  UTC-day allowance resets, with no timed wake-up.
- Clean up `done` and `failed` jobs too. Sweep our stopped/exited/unknown/
  offline instances and our orphaned rentals, including running ones,
  even if their job record is missing. Clear orphan schedules only after
  their target instances are confirmed gone.

Use the full B §2 status rule: empty stdout or `"error": true` on stderr
means an API problem, not a missing instance. A row with null actual
status is provisioning. Accept a null instance response as gone after
the row has been seen, or after two consecutive nulls. Error status
messages and stopped intended/actual status are failed starts. The CLI's
exit code alone is not evidence.

### 5. Submission

- `/api/create` validates the URL and synchronously saves it in the job
  record before acknowledging acceptance. Wake the coordinator, which
  rents and fetches/uploads in parallel with the image pull. Restarting
  the container resumes fetching from the saved URL. No pipeline stage is
  worth moving to the web container (requirement 4, C §3).
- `/api/upload` verifies the full request body arrived and uploads the
  input durably before acknowledging acceptance or renting. Persist its
  key in the job record. If recording or record persistence fails, return
  an error; an incomplete recording must never become an accepted job.
- Keep inputs under `sources/<job-id>/`, already skipped by web startup
  sync. Retain the uploaded original for restartable conversion. Publish
  exactly one complete `source.<ext>` there after fetching/conversion;
  persist its key and mark preparation ready only after successful upload.
  A restart checks for that complete object before repeating preparation.
  Source download and conversion have their own time limits.
- The worker uses its existing S3 key to wait for and fetch that source
  under the known input prefix, within the attempt deadline. It discovers
  the final suffix from the published object; a URL/video does not require
  guessing the filename before fetching. Atomic object upload separates
  waiting for publication from measuring a host's download speed.
- Meter changes are rejected while a version has open work or pending
  cleanup. For a completed cloud GPU version, save the new setting and
  generation together in the trusted record and enqueue regeneration.
  Restore cached onsets and the real source; regenerate every requested
  variant. Old `done` markers cannot satisfy the new generation. The
  current local cloud rerun lacks dependencies (C §5) and must not run.

### 6. Host record and blocklist

Keep `machine_id`, `host_id`, `public_ipaddr`, outcome, pull time and
bucket speed inside each attempt. Host identity comes from Vast; worker
measurements are diagnostic. Derive the roadmap's host record and recent
failure exclusions from these attempts, with no separate append-only file.
The offer query uses `public_ipaddr notin [...]` for slow routes and
`machine_id notin [...]` for broken boxes (server filters, B §6).

### 7. Page and docs

Versions with a job record read state and generation from it, plus matching
`done` markers and the current attempt's log. Legacy versions keep the
`sonification.ogg` rule. Show "trying another machine (attempt 2 of 5)",
"checking the previous rental", "daily rental limit reached", and
"failed, try again" as appropriate. Retry is unavailable until the previous
rental and any uncertain creation are resolved.

Meter and delete guards read durable job state, not just `RUNNING`. Deleting
an idle version removes its job record and inputs as well as its results.
README/webapp.md explain page closure, retry and the remaining scheduling
crash window. Replace operations.md's "keep the page open" caveat with
continuation on the next visit. Update gpu-workers.md for the baked worker,
scheduled deletion, confirmed cleanup and removal of the idle watchdog.

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
- **Cost guardrails**: reserve attempts before renting, enforce both rental
  caps, and set explicit numeric rate and time limits for offers and work.
  Validate them against the actual server-side deletion delay before
  enabling automatic rentals. Include disk/network charges and reject an
  over-budget fifth, fixed-price offer too. Keep `--cancel-unavail` (F3)
  and the sweeper (F7). Storage bills during the pull and for up to ~5 min
  after destruction (B §7); the creation/scheduling crash window remains.

## Test results (2026-10-01)

Both tests cost ≈ $0.003 (Vast) + €0.01 (Scaleway); everything they
created is deleted.

**T1 — CPU without a request.** A throwaway container with the webapp's
settings (1 GB, 500 mvCPU, sandbox v2, `python:3.12-slim` with an inline
probe) ran a thread that logged a busy-loop count every 10 s. Requests: one
instant GET at 17:31:52, a 120 s request at 17:34:52–17:36:52, then none.
The thread ran at the same rate throughout — median 13.2k loops / 10 s
before the long request, 13.5k during it, 13.4k in the 17 min after
(≈ 8.9 s CPU per 10 s in every phase). The last tick was 17:53:49, so the
instance stopped ≈ 17 min after the request ended. **No CPU throttling
between requests**; the earlier "keep the page open to keep the job
moving" belief was wrong — only scale-to-zero ends the work.

**T2 — Vast behaviour** (cheapest GPUs, `python:3.12-slim`, `--disk 10`):

- `CONTAINER_API_KEY` (64 chars) and `CONTAINER_ID` are injected into any
  image, not just Vast's. From inside, the key could read its own instance
  (200) and `DELETE` it (200 → `{"instances": null}`, audit-logged under its
  own key id from the host's IP), but not list instances (410), read the
  account (401) or relabel another instance (401 "constraint on id"). The
  create response also returns this key to the renter as `instance_api_key`.
- A 4000-character `--env` value and two 358-character presigned URLs
  arrived intact. Onstart ran ≈ 57 s after creation (small image).
- A label with `/` (`probe/t2-a`) is stored and returned verbatim.
- `--cancel-unavail` works for bids: half the market price with the flag →
  HTTP 410 `no_such_ask`, no instance; the same offer at 1.25× with the flag
  → created and running. Without the flag, a below-market bid creates an
  instance parked as `stopped` (`"success": false`) — F3 reproduced.
- A Vast scheduled job (`POST /commands/schedule_job/`, `request_method:
  DELETE`, `api_endpoint: /api/v0/instances/<id>/`, `frequency: HOURLY`)
  created at 17:33 fired at 18:00:14 (`min_of_the_hour: 0`), from Vast's
  own servers under a separate key id, and destroyed the parked instance.
  Not tested: whether `min_of_the_hour` can be set at creation.
- Not reproduced: why the 10-01 watchdog stayed silent (the test called
  DELETE from a fresh small image, not the idle loop on our image). The
  design drops the idle watchdog, so this matters less.

## Verifying the implementation

Use mocked API calls for claim/accounting checks, then fault injection on
cheap real rentals. Assert the following, not just that a retry finishes:

- Concurrent submissions and request wake-ups create one claim/rental;
  failed job writes create none. Five-rental and daily caps survive restart.
- Kill the coordinator after persisting a claim, immediately after Vast
  creates the rental, and before/after saving the deletion schedule. Recover
  by label and schedule inspection; ambiguous creation never issues another
  create. A claim left before the create call waits for inspection rather
  than expiring into a rental. Demonstrate the unguarded scheduling crash
  window until the next visit.
- Close the page and restart mid-fetch, mid-upload and mid-conversion.
  Accepted uploads retain their input; incomplete uploads are rejected.
  Failed input preparation cleans up without five identical rental retries.
- Destroy the host mid-pull and mid-variant. A replacement restores the
  shared grid and cached onsets and skips completed variants. Check that
  its output uses the same raw-bar setting and current generation.
- Kill the worker and block its bucket route (`iptables` drop to
  s3.fr-par.scw.cloud). Transfers and the attempt end within their limits.
  A healthy but quiet stage is allowed to continue until its deadline.
- Kill the worker after publishing all completion markers but before its
  DELETE, and fail the DELETE call. Completed jobs still get cleaned up.
  Keep the deletion schedule until Vast confirms absence, then remove it.
- Reject meter changes and deletion during open work or pending cleanup.
  Change the meter after completion; old markers cannot finish the rerun.
  Restart during regeneration and verify the new grid, audio and score agree.
- Probe scheduler minute selection and record actual firing times. Reject
  offers beyond the chosen price ceiling, including fixed-price try 5.
  Check `vastai show instances` and `vastai show invoices` for destroyed
  instances and actual costs, and check for leftover scheduled jobs.

Keep runnable checks for these state transitions. Preserve T1/T2 above as
historical results; the new design's checks have not been run yet.
