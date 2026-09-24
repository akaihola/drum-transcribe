# Running on atom (NixOS laptop)

## The server

Runs as a systemd user service (survives agent sessions):

```bash
systemctl --user status|restart drum-transcribe
```

Unit: `~/.config/systemd/user/drum-transcribe.service`, runs
`uv run drum-transcribe serve output --port 8765` in the repo.

**A restart can silently do nothing:** a `drum-transcribe serve` started by
hand keeps port 8765, so the unit crash-loops on `Address already in use`
while the old process goes on answering — and `systemctl --user is-active`
still prints `active` during the auto-restart window, so it looks fine. When
a change has to be live, check who owns the port: `ss -tlnp | grep 8765`
should name the unit's PID (`systemctl --user show -p MainPID
drum-transcribe`). Otherwise kill the stray process and restart. Found on
2026-09-21, when a security fix looked deployed but an orphan from the
previous evening was still serving the code it fixed.

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
  Cloudflare `vempai.men` zone, **proxied**, pointing at the container endpoint
  https://drumtranscribe1eb07827-webapp.functions.fnc.fr-par.scw.cloud, which
  also still works). Browsers get Cloudflare's certificate; Cloudflare talks
  to Scaleway over HTTPS (zone SSL mode "Full"), where Scaleway's own
  certificate for the domain still lives.
- Loading page: the Cloudflare Worker `plokkaus-front`
  (`deploy/cloudflare/`, design in [loading-page-plan.md](loading-page-plan.md))
  answers page loads that the container doesn't answer within 2.5 s with a
  "Starting up…" page that reloads itself once the app is up. Routes:
  `plokkaus.vempai.men/*` → the Worker (fail open), `plokkaus.vempai.men/api/*`
  → no Worker, so the once-a-second polls don't count against the free
  plan's 100 000 Worker requests a day. Deploy after editing:
  `cd deploy/cloudflare && set -a && . ../../.secrets.cloudflare.env && set +a && npx wrangler@4 deploy`
  (then check the main route still has `request_limit_fail_open: true`:
  `GET /zones/<zone>/workers/routes`). **Off switch:** set the `plokkaus`
  DNS record back to "DNS only"; the site then works exactly as before,
  without the loading page. Proxying caps request bodies at 100 MB (free plan),
  so bigger uploads fail with 413; Scaleway alone accepted 120 MB.
- What it is: the same web pages as the local server, serving whatever is in
  the `drum-transcribe-results` bucket (see [gpu-workers.md](gpu-workers.md)).
  Local (in-container) processing does not work — the image has no ML
  dependencies — but adding songs/versions **with the "process on a rented
  cloud GPU" checkbox works**: the container uploads the source to the
  bucket and drives a Vast.ai instance through `deploy/run-on-gpu.sh`
  (ssh client + `vastai` + `boto3` are in the image;
  Creation is throttled for anonymous visitors, and changing existing
  results (feedback, meter switch) needs the password outright, via the
  secret env vars `CREATE_PASSWORDS`/`TOKEN_SECRET` (see
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
  and direct-download URLs work there (no yt-dlp/ffmpeg in the image), and
  only to public http(s) addresses — on this deployment `check_url` resolves
  the host and refuses private ones ([webapp.md](webapp.md) → Fetching a new
  version), so a visitor can't read the container's own network back out of
  `/files/…`.
  Caveats: serverless CPU is throttled between requests, so keep the
  version's page open while it processes (its 1 s status polling keeps the
  job moving); if the container is scaled away mid-job, the GPU instance's
  idle watchdog self-destructs it (see gpu-workers.md). `pipeline.log` is
  ephemeral — results persist only via the bucket.
- Data: at every container start, `deploy/sync_bucket.py` downloads the
  bucket into `/app/output` before the server starts, except audio files
  (WAV/MP3, ~95 % of the bytes): those become empty stand-ins, and the server
  answers requests for them with a redirect to a 12-hour bucket download
  link, so the audio streams straight from the bucket (boto3; credentials come
  from container env vars `S3_ACCESS_KEY`/`S3_SECRET_KEY` — the worker's
  restricted key, set as secret env vars on the container, never baked into
  the image; `S3_ENDPOINT`/`S3_REGION`/`S3_BUCKET` are plain env vars).
  Rented GPU hosts can put anything in that bucket, so the sync skips any
  object whose name would write outside `/app/output` (gpu-workers.md §3).
  The container scales to zero when idle, so each cold start re-syncs
  (~20 MB without audio; with audio it was 550 MB and ~70 s). The log line
  `container starting` marks when our start script begins — its gap to the
  first request is Scaleway's own start-up time. Logs: Scaleway Cockpit,
  queried with the read-only token in `.secrets.cockpit-logs.json`
  (Loki API: `curl -G -H "Authorization: Bearer $SECRET_KEY"
  https://4b1f9092-5364-45e2-9395-596638758a27.logs.cockpit.fr-par.scw.cloud/loki/api/v1/query_range
  --data-urlencode 'query={resource_type="serverless_container"}'`).
  New results appear after the next cold start (or a `redeploy`) — no image
  rebuild needed for data.
- How it's built (code changes only): `deploy/Dockerfile` — a slim Python
  image with just the web app code. Built and pushed on gogo (600 Mbit
  uplink; workflow verified 2026-09-21 — atom's ~11 Mbit uplink also
  manages this small image in a few minutes if gogo is unavailable):
  ```bash
  rsync -a pyproject.toml src deploy agent@gogo:drum-transcribe-build/ctx/
  # registry credentials: atom's podman logins live in the ephemeral
  # /run/user/1000/containers/auth.json — copy per push, remove after
  scp /run/user/1000/containers/auth.json agent@gogo:drum-transcribe-build/auth.json
  ssh agent@gogo 'cd drum-transcribe-build \
    && podman build -f ctx/deploy/Dockerfile -t rg.fr-par.scw.cloud/drum-transcribe/webapp:test ctx \
    && podman push --authfile auth.json rg.fr-par.scw.cloud/drum-transcribe/webapp:test \
    && rm auth.json'
  , scw container container redeploy <container-id> --profile drum-transcribe
  ```
  gogo notes: its podman resolves no short image names (every `FROM`
  must be fully qualified, e.g. `docker.io/python:3.12-slim`), and its
  disk is ~99 % full — fine for this 400 MB image, hopeless for the
  13 GB+ GPU image (see [gpu-workers.md](gpu-workers.md) § 1).
- Scaleway resources (profile `drum-transcribe`, region fr-par): registry
  namespace `drum-transcribe`, containers namespace `drum-transcribe`,
  container `webapp` (id 9a37c1c8-6bf7-4a65-bee0-44db504fd1d3, 1 GB RAM,
  500 mvCPU, scales to zero when idle — costs nothing while unused,
  as long as no open page is polling it; see
  [musescore-plugin.md](musescore-plugin.md) on the `/api/seek` poll).

## GPU workers

Heavy processing (especially mdx23c) can run on rented cloud GPUs for
a few cents per song (measured: $0.02–0.03 all-in, see its §5): see
[gpu-workers.md](gpu-workers.md) for the
image, worker script, storage bucket, and Vast.ai workflow.
