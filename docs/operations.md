# Running on atom (NixOS laptop)

## The server

Runs as a systemd user service (survives agent sessions):

```bash
systemctl --user status|restart drum-transcribe
```

Unit: `~/.config/systemd/user/drum-transcribe.service`, runs
`uv run drum-transcribe serve output --port 8765` in the repo.

**Claude Code sandbox note:** each Bash command gets its own network
namespace, so a server started inside the sandbox is unreachable from
anywhere else — start/restart it with sandbox disabled (or via systemctl).
Same reason `curl 127.0.0.1:8765` from a sandboxed command can't reach an
unsandboxed server.

## Network access

- The laptop's firewall, VPN setup, and LAN addresses are deliberately not
  documented here. When the server must be reachable from another machine
  (port 8765), ask the user — only they can open firewall ports or share
  the current address.

## Caches and heavy downloads (all gitignored)

- `.cache/torch` (Demucs + beat_this checkpoints), `.cache/hf`, `.cache/uv`.
  Sandbox blocks `~/.cache/torch` — the pipeline is always run with
  `TORCH_HOME`/`HF_HOME`/`XDG_CACHE_HOME` pointing into the repo
  (`ingest._env()` does this for web-started jobs).
- `.models/` — MDX23C checkpoint (417 MB), shared across projects.

## Misc

- `uv sync` inside the sandbox: `CC=$(readlink -f $(which gcc))` — the
  default `cc` is an sccache wrapper that can't start its server there.
- MuseScore conversion: see [notation-musescore.md](notation-musescore.md);
  never use `, mscore` (ambiguous package). The CLI command comes from
  `MUSESCORE_CMD` (default `musescore`); until MuseScore is installed
  properly it is set to `, musescore` in the systemd drop-in
  `~/.config/systemd/user/drum-transcribe.service.d/musescore.conf`
  (export the same var for manual pipeline runs).
- GPU: none locally; user has rental accounts and has pre-approved renting
  one when a workload genuinely needs it (batch/mdx23c-heavy work).
- Timings on this 16-core CPU: Demucs ≈ 0.4× song length, ADTOF seconds,
  MDX23C ≈ 10× song length.

## Cloud test deployment (Scaleway Serverless Containers)

A read-only copy of the review web app runs in Scaleway's cloud so it can be
viewed from anywhere without the laptop being on:

- URL: https://plokkaus.vempai.men/ — a custom domain (CNAME `plokkaus` in the
  Cloudflare `vempai.men` zone, DNS-only, pointing at the container endpoint
  https://drumtranscribe1eb07827-webapp.functions.fnc.fr-par.scw.cloud, which
  also still works). TLS certificate is issued and renewed by Scaleway.
- What it is: the same web pages as the local server, serving whatever is in
  the `drum-transcribe-results` bucket (see [gpu-workers.md](gpu-workers.md)).
  Local (in-container) processing does not work — the image has no ML
  dependencies — but adding songs/versions **with the "process on a rented
  cloud GPU" checkbox works**: the container uploads the source to the
  bucket and drives a Vast.ai instance through `deploy/run-on-gpu.sh`
  (ssh client + `vastai` + `boto3` are in the image;
  Creation is throttled for anonymous visitors via the secret env vars
  `CREATE_PASSWORDS`/`TOKEN_SECRET` (see
  [webapp.md](webapp.md) → Throttling; `drum-transcribe hash-password`
  makes entries). Their values live in the gitignored
  `.secrets.throttle.env` at the repo root on atom; TOKEN_SECRET must stay
  fixed there — changing it revokes every bypass cookie.
  **`scw container container update secret-environment-variables.*`
  REPLACES the container's whole secret map** — always pass all six
  secrets in one update, or startup crashes on the missing S3 keys
  (learned 2026-09-21). `deploy/container-start.sh` materializes
  credentials at startup from the
  secret env vars `S3_ACCESS_KEY`/`S3_SECRET_KEY`/`VAST_API_KEY`/
  `GPU_SSH_KEY_B64` — the last is the base64 of the dedicated
  `.secrets.gpu-ssh` ed25519 key at the repo root on atom). Only uploads
  and direct-download URLs work there (no yt-dlp/ffmpeg in the image).
  Caveats: serverless CPU is throttled between requests, so keep the
  version's page open while it processes (its 1 s status polling keeps the
  job moving); if the container is scaled away mid-job, the GPU instance's
  idle watchdog self-destructs it (see gpu-workers.md). `pipeline.log` is
  ephemeral — results persist only via the bucket.
- Data: at every container start, `deploy/sync_bucket.py` downloads the whole
  bucket into `/app/output` before the server starts (boto3; credentials come
  from container env vars `S3_ACCESS_KEY`/`S3_SECRET_KEY` — the worker's
  restricted key, set as secret env vars on the container, never baked into
  the image; `S3_ENDPOINT`/`S3_REGION`/`S3_BUCKET` are plain env vars).
  The container scales to zero when idle, so each cold start re-syncs
  (~100 MB → the first request after an idle period takes extra seconds).
  New results appear after the next cold start (or a `redeploy`) — no image
  rebuild needed for data.
- How it's built (code changes only): `deploy/Dockerfile` — a slim Python
  image with just the web app code. Stage a build context with
  `pyproject.toml`, `src/`, and `deploy/`, then:
  ```bash
  docker build -f deploy/Dockerfile -t rg.fr-par.scw.cloud/drum-transcribe/webapp:test <context>
  docker login rg.fr-par.scw.cloud -u nologin -p <scw-secret-key>
  docker push rg.fr-par.scw.cloud/drum-transcribe/webapp:test
  , scw container container redeploy <container-id> --profile drum-transcribe
  ```
- Scaleway resources (profile `drum-transcribe`, region fr-par): registry
  namespace `drum-transcribe`, containers namespace `drum-transcribe`,
  container `webapp` (id 9a37c1c8-6bf7-4a65-bee0-44db504fd1d3, 1 GB RAM,
  500 mvCPU, scales to zero when idle — costs nothing while unused).

## GPU workers

Heavy processing (especially mdx23c) can run on rented cloud GPUs for
a few cents per song (measured: $0.02–0.03 all-in, see its §5): see
[gpu-workers.md](gpu-workers.md) for the
image, worker script, storage bucket, and Vast.ai workflow.
