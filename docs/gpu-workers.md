# GPU workers: processing songs on rented cloud GPUs

The pipeline runs fine on a laptop CPU, but the mdx23c variant takes ~10×
the song length there. A rented cloud GPU does a whole song in a few
minutes for well under €0.01. This doc covers the pieces that make that
work and how to run one. Skim the Overview; read a numbered section only
when working on that piece.

## Overview

```
laptop                          GHCR                    rented GPU host (Vast.ai)
deploy/Dockerfile.gpu  --push-> ghcr.io/akaihola/  --pull-->  container
                                drum-transcribe-gpu        deploy/vast-worker.sh:
                                                             fetch song → run variants
                                                                  │
laptop  <--rclone sync--  Scaleway bucket  <--upload per variant--┘
output/<song>/<version>/  drum-transcribe-results
```

Local `output/` stays canonical (git-committed, served by the review web
app). The bucket is only transport; GPU hosts never see the repo, git, or
main credentials.

## 1. The image

`deploy/Dockerfile.gpu` → `ghcr.io/akaihola/drum-transcribe-gpu`
(public, so Vast hosts pull anonymously with no rate limits; tags:
`cu128-v1`, `latest`; ~8 GB compressed).

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
podman build -f .build-ctx-gpu/deploy/Dockerfile.gpu \
  -t ghcr.io/akaihola/drum-transcribe-gpu:latest .build-ctx-gpu
podman push ghcr.io/akaihola/drum-transcribe-gpu:latest  # atom is logged in to ghcr.io
```

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

`deploy/vast-worker.sh`, run inside the container on the GPU host.
Env in, results out: `SOURCE_URL` + `SONG`/`VERSION` (+ `VARIANTS`,
default both) and the S3 credentials; uploads
`output/<SONG>/<VERSION>/` (minus `stems/`, except the Demucs
`drums.wav` the page plays) to the bucket
**after each variant**, so a spot interruption loses at most one stage.
Fetches the static rclone binary at startup (~20 MB, seconds).

## 3. Storage and credentials

- Bucket: `drum-transcribe-results`, Scaleway fr-par,
  endpoint `https://s3.fr-par.scw.cloud` (~€0.01/GB/month).
- Workers authenticate with a **dedicated scoped key** (IAM application
  `drum-transcribe-worker`, object-storage-only, expires 2027-03-31),
  stored in the gitignored `.secrets.worker-s3.json` at the repo root.
  Rented hosts never see the main Scaleway or GitHub credentials.
- Pull finished results into the canonical tree, then commit them:
  `rclone sync s3:drum-transcribe-results output/` (configure rclone with
  the same key, or use `, scw object` / any S3 client).
- **Everything in the bucket is untrusted.** Every rented host gets the
  worker key, so a host operator can upload any file under any name —
  including names like `../../.bashrc` that try to escape the results
  folder and overwrite files on the laptop or in the cloud app. rclone
  blocks that by itself; the two places that copy the bucket with boto3
  (`deploy/gpu-session.sh run`, `deploy/sync_bucket.py`) check each name
  and skip anything landing outside the destination folder.

## 4. Renting a GPU (Vast.ai)

CLI is a dev dependency: `uv run vastai ...` (API key set via
`vastai set api-key`, stored in `~/.config/vastai`). Spot ("interruptible")
RTX 3090s in Europe run ~$0.09/h; a song costs well under a cent, so bid
10–20 % over the floor and don't agonize.

The whole cycle is wrapped in one command — rent, process, sync results
to `output/`, destroy:

```bash
deploy/run-on-gpu.sh <SOURCE_URL> <SONG> <VERSION> ["adtof mdx23c"]
```

When several songs (or retries of one song) are coming, open a
keep-alive session instead — the instance stays warm between jobs,
skipping the 1–10 min image pull, and any `run-on-gpu.sh` call (e.g.
from the web app) reuses it while it's open:

```bash
deploy/gpu-session.sh start [IDLE_MINUTES]     # rent; idle timeout, default 30
deploy/gpu-session.sh run <SOURCE_URL> <SONG> <VERSION> ["adtof mdx23c"]
deploy/gpu-session.sh status                   # instance id, or exit 1
deploy/gpu-session.sh stop                     # destroy
```

Safety net: the instance runs a watchdog (`--onstart-cmd`) that
destroys the instance *itself* after IDLE_MINUTES without job activity,
using the per-instance `CONTAINER_API_KEY` Vast injects into every
container (it can start/stop/destroy only that instance). So a crashed
or disconnected laptop can't leave the instance billing indefinitely —
worst case is the idle timeout, ~$0.05 at default settings. Jobs are
delivered over ssh, and `deploy/vast-worker.sh` is streamed from the
repo (not the baked copy), so worker changes need no image rebuild; the
worker touches `/tmp/alive` per variant to feed the watchdog. One gap:
the watchdog starts only after the image pull, so a host stuck pulling
is guarded by the caller's ssh-wait timeout (~22 min), not the watchdog.

The rented host is a stranger, and the job stream carries the worker's
S3 credentials, so ssh pins the instance's host key on first contact
(`StrictHostKeyChecking=accept-new` writing to `.gpu-known-hosts`,
wiped by `start` since each instance has its own key). Vast can't
publish the key in advance, so the very first connection of a session
is taken on trust; every later one is checked, which is what matters
for the long jobs this session exists for.

Spot-market hardening, each rule paid for by a real failure (2026-09-20):

- **ssh directly to the host's mapped port 22** (`public_ipaddr` +
  `ports["22/tcp"]`), never through `ssh*.vast.ai` — the proxy drops
  long-lived connections mid-job. Proxy is fallback only.
- **Filter offers by `verified=true cuda_max_good>=12.8`** (the image's
  CUDA), and still **assert `torch.cuda.is_available()` over ssh after
  start** — one "verified reliable" host had a driver that couldn't run
  CUDA 12.8 (error 804) and torch silently fell back to CPU.
- **Pick randomly among the 5 cheapest offers and retry `start` up to
  3×** (`run-on-gpu.sh`) — cheapest-first kept re-renting the same host
  that never finished pulling the image.
- **Bid 1.25× over the floor** — 1.15× got outbid between image load
  and container start (instance sits in `created`/`stopped`; destroy
  and re-rent rather than wait for the GPU to free up).
- **No progress bars over the job stream** (`TQDM_DISABLE=1` in the
  worker): tqdm floods the ssh stream, and a slow log consumer (the
  CPU-throttled cloud container) can stall the job via backpressure.

The web app's new-version form has a "process on a rented cloud GPU"
checkbox that drives this same script (see
[webapp.md](webapp.md#ingestion-jobs-ingestpy)), passing all three
variants including `fused`.

Manual steps, when debugging or doing something the wrapper doesn't:

```bash
# find offers: 1×3090, reliable, fast downlink (fast image pull)
uv run vastai search offers \
  'gpu_name=RTX_3090 num_gpus=1 reliability>0.98 inet_down>500 rentable=true verified=true cuda_max_good>=12.8' \
  --type=bid -o 'dph_total'

# launch one song (worker env; see deploy/vast-worker.sh header)
uv run vastai create instance <OFFER_ID> \
  --image ghcr.io/akaihola/drum-transcribe-gpu:latest --disk 40 \
  --onstart-cmd 'bash /app/deploy/vast-worker.sh' \
  --env '-e SOURCE_URL=... -e SONG=... -e VERSION=... -e S3_ACCESS_KEY=... -e S3_SECRET_KEY=...' \
  --bid_price 0.11

uv run vastai show instances            # watch status
uv run vastai logs <INSTANCE_ID>        # worker output; ends with "WORKER DONE"
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

Batching = a keep-alive session (`gpu-session.sh start`, then one `run`
per song). Spot pause/outbid is safe: every stage is cached and uploads
happen per variant; just relaunch elsewhere.

## 5. Costs (2026-09 figures)

| item | cost |
|---|---|
| RTX 3090 spot, EU | floor ~$0.08–0.13/h; we bid 1.25× → pay $0.10–0.17/h |
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
- The idle watchdog caps an abandoned instance at the idle timeout:
  ~$0.05 at the default 30 min.

Rule of thumb: **a song costs 2–3 cents; a whole failed rental costs
about the same; only an undetected-CPU host or a forgotten instance
costs more** — and both now have guards.

Alternatives considered and rejected on price or fit: Scaleway serverless
CPU (adtof-only viable at ~€0.03/song, mdx23c ~2 h/€0.60), managed L4 at
€0.79/h (fine for batches, ~9× spot price), hosted APIs (Music.AI,
Klangio: $0.40–3.60/song, black boxes — no intermediates for the review
loop).
