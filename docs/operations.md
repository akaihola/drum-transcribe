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
  never use `, mscore` (ambiguous package).
- GPU: none locally; user has rental accounts and has pre-approved renting
  one when a workload genuinely needs it (batch/mdx23c-heavy work).
- Timings on this 16-core CPU: Demucs ≈ 0.4× song length, ADTOF seconds,
  MDX23C ≈ 10× song length.
