Queue fixing these issues in the ordered backlog of `TASKS.md`. Make sure `TASKS.md` and the task descriptions are *not* committed or pushed to GitHub. Only push after all of them have been fixed and purged from `TASKS.md` and `docs/tasks`.

**Public site behaviour:**
- Anyone can pause or seek every visitor's player through `/api/seek` (`serve.py:1761-1766`).
- Request and upload sizes are unlimited.
- `/files/` lets anyone browse submitted links, logs, feedback and original uploads.
- There is an open redirect via `//` in `/files/` paths.

**Third-party loading:**
- No CSP; Verovio is loaded as unpinned "latest" (`serve.py:649`).
- Google Fonts and the YouTube player load for every visitor without consent, which is a GDPR question.

**Infrastructure:**
- The docs publish the Scaleway origin address (`docs/operations.md:73-78`), so Cloudflare and the planned scanner-blocking rule can be bypassed.
- Cloudflare SSL is set to "Full", not "Full (strict)", and there is no HSTS.

**Supply chain:**
- The Docker images ignore `uv.lock`, install ADTOF from an unpinned git HEAD, and run as root.
- Model checkpoints are downloaded without hash checks and loaded with full pickle (`beats.py:93`, `separate.py:32-35`).