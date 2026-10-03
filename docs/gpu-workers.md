# GPU workers: processing songs on rented cloud GPUs

The pipeline runs fine on a laptop CPU, but the mdx23c variant takes ~10×
the song length there. A rented cloud GPU does a whole song in a few
minutes for well under €0.01. This doc covers the pieces that make that
work and how to run one. Skim the Overview; read a numbered section only
when working on that piece.

## Overview

```
laptop                          GHCR                    rented GPU host (Vast.ai)
deploy/Dockerfile.gpu  --push-> ghcr.io/akaihola/  --pull-->  container, onstart:
                                drum-transcribe-gpu        deploy/vast-worker.sh:
                                                             fetch song → run variants
cloud web app (Scaleway)                                          │
coordinator.py: rents, guards, ──rent/delete (Vast API)──>        │
syncs results into the page     <──results per variant── Scaleway bucket
                                                  drum-transcribe-results
laptop  <--rclone sync--  bucket
output/<song>/<version>/
```

Only the cloud web app rents (since 2026-10-03): a song is submitted
through its form with "process on a rented cloud GPU", and the laptop
pulls finished results with `rclone sync`. Local `output/` stays
canonical (git-committed, served by the laptop's review web app). The
bucket is transport; GPU hosts never see the repo, git, or main
credentials. How the web app keeps a job going through closed pages,
crashed hosts and container restarts:
[gpu-resilience-handoff.md](gpu-resilience-handoff.md).

## 1. The image

`deploy/Dockerfile.gpu` → `ghcr.io/akaihola/drum-transcribe-gpu`
(public, so Vast hosts pull anonymously with no rate limits; tags:
`cu128-v1`, `latest`; ~8 GB compressed). Since 2026-09-25 `latest` also
contains MuseScore for the .mscz export (see
[notation-musescore.md](notation-musescore.md)); `cu128-v1` predates it.

Design decisions, each of which broke something before it was made:

- **Base `vastai/pytorch:2.11.0-cu128-...-py311` (pinned dated tag).**
  Vast's own base images are pre-cached on many hosts → cache-hit hosts
  only pull our ~4 GB of layers. Must be a **torch 2.11** tag: torchaudio
  is frozen upstream at 2.11 and its native library refuses to load
  against newer torch (the `-auto` tags run torch 2.14).
- **Python env is `/venv/main`**, not system python — that's where the
  base keeps torch. Everything installs and runs via
  `/venv/main/bin/...`.
- **Install is `uv pip install` with two pyproject rewrites** (container
  copy only, repo file untouched): `adtof-pytorch` becomes a direct git
  reference (it is not on PyPI; `[tool.uv.sources]` is invisible to
  `uv pip`/pip), which in turn needs hatchling's
  `allow-direct-references`; and the `[tool.uv]` section is stripped so
  torchaudio resolves to the CUDA build, not the laptop's pinned CPU
  index.
- **All model checkpoints are baked in** (`/app/.cache`, `/app/.models`;
  ~1.7 GB: htdemucs, beat_this, MDX23C; ADTOF ships inside its package).
  No startup downloads, pinned bytes, one failure point. Workers must run
  with **CWD `/app`** — `.models/` resolves relative to CWD.

Rebuild + push (layers ordered deps → models → code: the deps layer
installs from `pyproject.toml` alone, so code-only changes rebuild and
re-push only megabytes — fine even on atom's 11 Mbit uplink, because
GHCR keeps the unchanged multi-GB layers):

```bash
# stage a clean context — repo .cache also holds unrelated junk (uv,
# nix, fontconfig…), so pick just the two model-cache dirs
mkdir -p .build-ctx-gpu/.cache
cp -al .cache/torch .cache/hf .build-ctx-gpu/.cache/
cp -al .models src deploy .build-ctx-gpu/
cp pyproject.toml .build-ctx-gpu/
TAG=$(date +%F)  # then set coordinator.IMAGE to this tag
podman build -f .build-ctx-gpu/deploy/Dockerfile.gpu \
  -t ghcr.io/akaihola/drum-transcribe-gpu:$TAG \
  -t ghcr.io/akaihola/drum-transcribe-gpu:latest .build-ctx-gpu
podman push ghcr.io/akaihola/drum-transcribe-gpu:$TAG
podman push ghcr.io/akaihola/drum-transcribe-gpu:latest
```

Pushing needs `podman login ghcr.io -u akaihola` with a *classic* GitHub
token that has `write:packages` (the login is lost on reboot; the `gh`
CLI's fine-grained token is refused: "does not match expected scopes").

The web app rents the dated tag named in `coordinator.IMAGE`, so a new
image goes live with the web app version that expects it, and the worker
(baked into the image) always matches its coordinator.

Before building, confirm `.cache/torch/hub/checkpoints/` holds all ten
files (9 htdemucs `*.th` + `beat_this-final0.ckpt`) — the htdemucs ones
vanished from the repo cache once (2026-09-21; restored from
`~/.cache/torch/hub/checkpoints/`, where torch hub actually downloads
them). A context missing them would build an image that breaks the
no-startup-downloads design without any build error.

Build on atom, not gogo (checked 2026-09-21): gogo's 226 GB disk sits
at ~99 % (~6 GB free after pruning), and this base image alone unpacks
to 13 GB — gogo can neither build nor even pull it. Its 600 Mbit
uplink still earns its keep for the small webapp image
([operations.md](operations.md)); the layer reordering above is what
made atom's slow uplink acceptable here.

## 2. The worker

`deploy/vast-worker.sh`, baked into the image and started by the
instance's onstart command (`bash /app/deploy/vast-worker.sh`); no ssh.
The web app passes everything in the instance's env: `SONG`, `VERSION`,
`VARIANTS`, `GENERATION`, `RAW_BARS`, `CLAIM` (the rental's id),
`SOURCE` (the bucket prefix `sources/<job>/` where the recording
appears), `DEADLINE` (unix time) and the worker S3 key. In order:

1. checks that torch sees the GPU (a host whose driver can't run the
   image's CUDA would otherwise compute on the CPU at GPU prices);
2. waits for `sources/<job>/source.<ext>` (the web app may still be
   fetching it), then downloads it within `20 s + size / 500 kB/s`. That is the
   bucket speed test: a host whose route to Scaleway crawls (2–12 kB/s
   on 2026-10-01) gives up before any GPU work;
3. restores `beats_raw.json` and any `<variant>/onsets.json` from an
   earlier host, sets or clears `keep-raw-bars`;
4. per variant, unless `<variant>/done` already holds this generation:
   runs the pipeline, uploads the version (the recording, beat grid, the
   Opus copies of the Demucs stems and the variant's files, never the
   FLACs, the MDX23C kit stems, done markers, `feedback.json` or the
   raw-bar flag), then writes `<variant>/done` with the generation;
5. on success, failure or the deadline (everything runs under
   `timeout`), deletes its own instance through Vast's API with the
   per-instance `CONTAINER_API_KEY`, up to three tries.

Its log goes to `<SONG>/<VERSION>/workers/<CLAIM>.log` every 60 s; the
page's progress bars read it. Every rclone transfer has connect and idle
timeouts plus a total `--max-duration`. Vast reruns onstart if it resumes
a stopped instance; every step above is repeatable and the deadline is
absolute.

## 3. Storage and credentials

- Bucket: `drum-transcribe-results`, Scaleway fr-par,
  endpoint `https://s3.fr-par.scw.cloud` (~€0.01/GB/month). Inputs go
  under `sources/<job>/` (the uploaded original, the published
  `source.<ext>`); results under `<song>/<version>/`.
- Workers authenticate with a **dedicated scoped key** (IAM application
  `drum-transcribe-worker`, expires 2027-03-31), stored in the gitignored
  `.secrets.worker-s3.json` at the repo root. Rented hosts never see the
  main Scaleway or GitHub credentials. Since 2026-10-03 its policy grants
  objects only (`ObjectStorageObjectsRead/Write/Delete` on project
  dallape), so a host can no longer change the bucket's CORS, versioning
  or lifecycle rules. That also denies HeadBucket, so rclone needs
  `--s3-no-check-bucket` (the worker sets `RCLONE_S3_NO_CHECK_BUCKET`).
- Job records live in a second bucket, `drum-transcribe-jobs`, whose
  bucket policy admits only the web app's own key (IAM application
  `drum-transcribe-webapp`, objects only, expires 2027-09-28, gitignored
  `.secrets.jobs-s3.json`) and the owner's user id. The worker key is
  refused there (checked 2026-10-03), so a host can't touch job state.
- Pull finished results into the canonical tree, then commit them:
  `rclone sync s3:drum-transcribe-results output/ --exclude 'sources/**'`
  (configure rclone with the worker key, or use `, scw object` / any S3
  client).
- **Everything in the results bucket is untrusted.** Every rented host
  gets the worker key, so a host operator can upload any file under any
  name — including names like `../../.bashrc` that try to escape the
  results folder and overwrite files on the laptop or in the cloud app.
  rclone blocks that by itself; the places that copy the bucket with
  boto3 (`deploy/sync_bucket.py`, `coordinator.py` collecting results)
  check each name and skip anything landing outside the version folder.
  Done markers count only when they name the generation in the trusted
  job record, and instance ids are taken only from Vast's own listing.

## 4. Renting a GPU (Vast.ai)

The cloud web app's coordinator (`src/drum_transcribe/coordinator.py`)
rents through Vast's REST API (`vast.py`; the `vastai` CLI exits 0 even
on HTTP errors, so its exit code proves nothing). Spot ("interruptible")
RTX 3090s cost ~$0.11–0.17/h with the bid below. Each rental is labelled
`drum-transcribe/<job>/<claim>`; only that namespace is the coordinator's
to clean up, so manual rentals with other labels are left alone.

Rules, each paid for by a real failure:

- **Filter offers by `verified=true cuda_max_good>=12.9`** (the base
  image's CUDA), and still have the worker check `torch.cuda.is_available()`
  — one "verified reliable" host had a driver that couldn't run the
  image's CUDA (error 804) and torch silently fell back to CPU. The filter
  must match the base image's CUDA (12.9), not torch's build (cu128): a
  driver that stops at 12.8 makes the container try NVIDIA's
  forward-compatibility layer, which GeForce cards like the 3090 lack →
  error 804. Filtering on 12.8 let such a host (driver 570.86) through
  on 2026-09-28.
- **Pick randomly among the 5 cheapest offers** — cheapest-first kept
  re-renting the same host that never finished pulling the image. Hosts
  that failed in the past week are left out of the search itself:
  `machine_id notin [...]` for broken boxes and stuck pulls,
  `public_ipaddr notin [...]` for slow routes to the bucket (one site can
  hold several machines).
- **Bid 1.25× over the floor, with `cancel_unavail`** — 1.15× got outbid
  between image load and container start, and without `cancel_unavail` a
  bid that can't start at once is parked as `stopped` (still billing
  storage); with it Vast refuses the bid (HTTP 410) and nothing is
  created. Tries 1–4 bid; try 5 rents at the fixed on-demand price,
  which can't be outbid.
- **Give up on an instance that won't run**: Vast says it is
  stopped/exited/unknown/offline or its status message reports an
  error, or it hasn't started running 15 min after renting (stuck
  pulling the image). A healthy rental (2026-09-25) spent its whole
  8.5 min pull as `loading`.
- **A scheduled DELETE guards every rental**: right after creating it,
  the coordinator asks Vast's own servers to delete it from its deadline
  on (`POST /api/v0/commands/schedule_job/`, hourly until it is gone).
  That covers a stuck image pull, a dead worker and a sleeping web app
  alike. Vast runs such hourly jobs at minute 0 of every hour from the
  hour that *contains* the start time (2026-10-03: a guard starting at
  13:22 deleted a healthy rental at 13:00), so the guard starts just
  past the first full hour after the deadline and fires 0–60 min after
  it. Don't touch `min_of_the_hour`: a job whose minute was changed
  afterwards never ran. The guard is removed only once Vast no longer
  lists the instance.
- **Read Vast's answers by the rule in research B §2**: no answer or an
  HTTP error is "unknown", never "gone"; an instance is gone only when
  the listing no longer has it (twice in a row if it was never seen);
  a create without a clear answer is never repeated. Its label, then
  the account's audit log, tell whether it happened.

Manual rentals still work for debugging; label them anything not
starting with `drum-transcribe/`.

Manual steps, when debugging:

```bash
# find offers: 1×3090, reliable, fast downlink (fast image pull)
uv run vastai search offers \
  'gpu_name=RTX_3090 num_gpus=1 reliability>0.98 inet_down>500 rentable=true verified=true cuda_max_good>=12.9' \
  --type=bid -o 'dph_total'

# launch one song by hand (worker env: see deploy/vast-worker.sh header;
# the recording must be in the bucket under SOURCE; DEADLINE = unix time)
uv run vastai create instance <OFFER_ID> \
  --image ghcr.io/akaihola/drum-transcribe-gpu:latest --disk 40 \
  --label manual-test --cancel-unavail \
  --onstart-cmd 'bash /app/deploy/vast-worker.sh' \
  --env '-e SONG=... -e VERSION=... -e VARIANTS=adtof -e GENERATION=1 -e RAW_BARS=0
         -e CLAIM=manual -e SOURCE=sources/<job>/ -e DEADLINE=... -e S3_ACCESS_KEY=... -e S3_SECRET_KEY=...' \
  --bid_price 0.15

uv run vastai show instances            # watch status
uv run vastai logs <INSTANCE_ID>        # onstart output; the worker's own log
                                        # is workers/<CLAIM>.log in the bucket
uv run vastai show scheduled-jobs       # the web app's deletion guards
uv run vastai destroy instance <ID>     # ALWAYS destroy when done —
                                        # stopped instances still bill storage
```

Lessons from the first test run (2026-09-20, $0.04 total):

- `--onstart <file>` upload silently did NOT deliver the script (only
  Vast's stub arrived), which is why the worker script is baked into the
  image and launched with `--onstart-cmd`.
- `--env` values reach the container correctly, presigned URLs included.
  But if you ever copy env into a shell file manually, quote the values —
  presigned URLs contain `&`.
- Fallback when onstart misbehaves: `vastai attach ssh <ID> "$(cat
  ~/.ssh/id_ed25519.pub)"`, then ssh in (`vastai ssh-url <ID>`), env is in
  `/proc/1/environ`, run `bash /app/deploy/vast-worker.sh` by hand.
- GPU timings: both variants of a 4-min song ≈ 5 min total; mdx23c alone
  ≈ 1 min (vs ~40 min on the laptop CPU).

Timed run (2026-09-25, 4.6 min song, all 3 variants, RTX 3090 at
$0.152/h, 20 min wall clock, **$0.033**):

| step | time |
|---|---|
| image pull (host at 861 Mbit/s) | 8.5 min |
| GPU check + fetching the recording | 20 s |
| adtof: Demucs 20 s, beats 25 s, ADTOF 36 s | 1.4 min |
| mdx23c: MDX23C split 36 s, onsets 12 s | 0.9 min |
| fused: ADTOF 13 s, refining 7 s | 0.4 min |
| uploads to the bucket (after each variant) | 4 + 2 + 2 min |
| syncing results to the laptop | 40 s |

The GPU work itself is under 3 min; the per-variant uploads (~110 MB
in total, mostly WAVs) took 8 min at this host's upload speed, and
the image pull another 8.5. The progress bars' GPU estimates
(`progress.py`) come from this run. Since 2026-10-03 the stems go up as
Opus, about a quarter of those bytes.

Spot pause/outbid is safe: the worker's caches and per-variant uploads
let the next host carry on where the last one stopped.

## 5. Costs (2026-09 figures, limits from 2026-10-03)

| item | cost |
|---|---|
| RTX 3090 spot | floor ~$0.09–0.15/h; we bid 1.25× → pay $0.12–0.18/h with the disk |
| one song, all 3 variants | **$0.02–0.03 all-in** (measured, see below) |
| GHCR public image | €0 (storage and bandwidth free) |
| bucket storage | ~€0.01/GB/month; a song's results ≈ 50 MB |
| cold start | ~1–3 min on a cache-hit host, up to ~10 min otherwise |

Measured billing (`vastai show invoices`, 2026-09-20/21 test campaign).
A Vast invoice line has three parts: **GPU** (billed only while the
container runs), **storage** (billed for the instance's whole lifetime —
including while pulling the image, stopped, or outbid; the 40 GB disk
runs $0.007–0.05/h depending on host), and **upload/download**
(~$0.001/job at our volumes). The two successful production-path runs:

| run | GPU time | GPU | storage | net | total |
|---|---|---|---|---|---|
| 10-min song, 3 variants + image pull | 0.16 h @ $0.167 | $0.027 | $0.002 | $0.001 | **$0.030** |
| 3-min song, 3 variants + image pull | 0.10 h @ $0.135 | $0.014 | $0.005 | — | **$0.019** |

Failure economics, from the same campaign (13 instances, ~$0.25 total —
the hardening rules in §4 exist to keep these rare):

- A host stuck pulling the image, or outbid before start, bills
  **storage only** ($0.003–0.03) — annoying, not scary.
- A host with a broken CUDA driver is the worst case: it *processes*, on
  CPU, slowly, billing GPU rate for garbage throughput ($0.02 for one
  half-finished job). The post-ssh `torch.cuda.is_available()` check now
  catches this in seconds (~$0.001).
- (The idle watchdog of that time is gone; deadlines and the deletion
  guard below replace it.)

Limits the web app enforces (`coordinator.py`, decided 2026-10-03):

- offers up to **$0.18/h** with the disk (plus our own ~0.2 GB of
  transfers on hosts that bill bandwidth); a pricier fifth, fixed-price
  try waits instead;
- **5 rentals per generation** of a version, **30 per UTC day** in all;
- a rental must be running 15 min after it was rented, and its worker
  stops and deletes the instance 30 min after it was rented.

What one rental can cost at $0.18/h: a normal song 2–4 ¢; a host that
never finishes loading the image < 1 ¢ (disk only); a host that hangs
while running ~7 ¢ (its worker deletes it at the deadline). In the rare
worst case the worker can't delete it while the site sleeps, and it runs
until Vast's scheduled DELETE, up to an hour past the deadline: ~28 ¢.
A day of nothing but such failures could reach 30 × 28 ¢ ≈ $8 in
theory; realistic failure days stay around a dollar. Measured on
2026-10-03: 2.2 ¢ for a 4.6-min song on one host, 3.3 ¢ for a song whose
first two hosts were killed on purpose.

Alternatives considered and rejected on price or fit: Scaleway serverless
CPU (adtof-only viable at ~€0.03/song, mdx23c ~2 h/€0.60), managed L4 at
€0.79/h (fine for batches, ~9× spot price), hosted APIs (Music.AI,
Klangio: $0.40–3.60/song, black boxes — no intermediates for the review
loop).
