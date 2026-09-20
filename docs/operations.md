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

- URL: https://drumtranscribe1eb07827-webapp.functions.fnc.fr-par.scw.cloud
- What it is: the same web pages as the local server, but with a snapshot of
  one song version (`dancing-through-life/taustanauha`, both variants) baked
  into the container image. Uploading songs or starting new processing does
  NOT work there — the image has no ML dependencies.
- How it's built: `deploy/Dockerfile` — a slim Python image with only the web
  app code plus the sample results (~180 MB). Stage a build context with
  `pyproject.toml`, `src/`, and the chosen `output/<song>/<version>` subset
  (drop `stems/`), then:
  ```bash
  docker build -t rg.fr-par.scw.cloud/drum-transcribe/webapp:test <context>
  docker login rg.fr-par.scw.cloud -u nologin -p <scw-secret-key>
  docker push rg.fr-par.scw.cloud/drum-transcribe/webapp:test
  , scw container container redeploy <container-id> --profile drum-transcribe
  ```
- Scaleway resources (profile `drum-transcribe`, region fr-par): registry
  namespace `drum-transcribe`, containers namespace `drum-transcribe`,
  container `webapp` (id 9a37c1c8-6bf7-4a65-bee0-44db504fd1d3, 1 GB RAM,
  500 mvCPU, scales to zero when idle — costs nothing while unused).
- Both code and the data snapshot only update when the image is rebuilt
  and pushed and the container redeployed (steps above). Planned
  improvement: sync data from the `drum-transcribe-results` bucket at
  container startup instead of baking it in (see
  [gpu-workers.md](gpu-workers.md) for the bucket).

## GPU workers

Heavy processing (especially mdx23c) can run on rented cloud GPUs for
under a cent per song: see [gpu-workers.md](gpu-workers.md) for the
image, worker script, storage bucket, and Vast.ai workflow.
