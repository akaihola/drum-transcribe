Queue fixing these issues in the ordered backlog of `TASKS.md`. Make sure `TASKS.md` and the task descriptions are *not* committed or pushed to GitHub. Only push after all of them have been fixed and purged from `TASKS.md` and `docs/tasks`.

**The anonymous limit can be bypassed by sending requests at the same moment.** The limit is checked at the start (`serve.py:1875`, `1718`), but the "created" marker is written only at the end (`serve.py:1917`, `1725`). In a local test, 5 parallel anonymous uploads all succeeded. With GPU switched on, each one is a paid rental.

**Gaps in the guard that stops the site fetching from private networks:**
- The server's address is looked up once for the check and again for the download (DNS rebinding, `ingest.py:153-164` vs `201-205`).
- ffmpeg may fetch further addresses named inside a downloaded playlist file.
- `docs/webapp.md:143-146` describes these gaps publicly.

**Uploaders' private metadata is published.** ffmpeg's normal output goes into the public `pipeline.log` (`ingest.py:219-225`), and that output includes a phone video's GPS position, phone model and recording time. Audio uploads are kept byte for byte, with all their tags, and served as the "original" (`ingest.py:212-216`). **Fix:** `-map_metadata -1` and quieter ffmpeg logging.

**One link with a line break inside can break the site's song list for every visitor.** A forged line in the log crashes the date parsing in `progress.py:147-160`, and the list stays broken until that version is deleted.

**The public GPU image leaks your approximate location.** `ghcr.io/akaihola/drum-transcribe-gpu:2026-10-03` (also tagged latest) can be downloaded by anyone. `Dockerfile.gpu:40` copies all of `deploy/` and there is no `.dockerignore`, so the image includes `deploy/cloudflare/.wrangler/cache/cf.json`. That file holds the city, postal code, latitude/longitude and ISP of the network where wrangler ran, probably your home. **Fix:** add a `.dockerignore`, rebuild, and delete the old tags on GHCR. (2026-10-10: queued as part of task [16], which rebuilds the image anyway.)

**No security issues in public repository:** If any descriptions of security issues have accidentally been committed, rewrite history to remove traces of them. Also force push to GitHub to clean them up there too.

## Queued, 2026-10-15

- Anonymous limit race → [17].
- Private-network fetch gaps and the `docs/webapp.md` note → [18].
- Uploaders' metadata → [19].
- Line break in a link breaks the song list → [20].
- GPU image location leak → already in [16] (step 2; the code part is
  commit `3271352`, rebuild and GHCR cleanup pending atom access).
- History purge and the eventual push → [21], after all of the above.

Checked on 2026-10-15: GitHub has none of the security task notes
(`git log -p --remotes=origin -- TASKS.md docs/tasks` finds none of them).
They exist only in unpushed local history from `dde23b6` on, because the
tracker automation commits `TASKS.md` and `docs/tasks/`; [21] removes them.
Nothing was force-pushed, as nothing needed cleaning on GitHub.
