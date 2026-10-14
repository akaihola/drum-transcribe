Queue fixing these low priority security issues in the ordered backlog of `TASKS.md`. Make sure `TASKS.md` and the task descriptions are *not* committed or pushed to GitHub. Only push after all of them have been fixed and purged from `TASKS.md` and `docs/tasks`.

## Personal info in the public repo (your call; none is dangerous alone)

- Tailnet name and the laptop's MagicDNS hostname, in commit `91da1b5`. It was removed later but is still in history.
- Machine names, username, home paths and home-network details in `AGENTS.md`, `docs/operations.md` and `docs/gpu-workers.md`.
- Cloud account structure and Vast hosts' IP addresses in the research docs.

## Other

The dependency vulnerability scan (pip-audit) couldn't run in the sandbox. A reviewer recalled advisories for pillow 12.2.0 and cryptography 49.0.0 from memory; that is unconfirmed.