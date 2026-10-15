---
depends_on: [11]
---
# Deploy the GPU host fix

Task [11] stopped handing the results-bucket key to rented GPU machines,
but only in the code (2026-10-06, on gogo). Until this task is done, the
cloud web app still gives the key to every machine it rents, so **don't
start cloud GPU jobs** before then. On 2026-10-10 Vast.ai reported that one
of our rentals ran on a machine intruders had got into (task [15], "Vast.ai
incident"). This task is first in the queue because of that.

This is task [11]'s "Still to do" steps 1–3, 5 and 6, plus the GPU image
leak from task [12], which must be fixed before the build.

## Steps (on atom)

1. Bring main from `agent@gogo:~/prg/drum-transcribe` to atom's clone
   without GitHub (task [12] forbids pushing), e.g.
   `git pull --ff-only agent@gogo:prg/drum-transcribe main`.
2. Stop the image leaking your location (from [12]). `Dockerfile.gpu`
   copies all of `deploy/`, including `deploy/cloudflare/.wrangler/cache/cf.json`
   (city, postal code, coordinates and ISP of the network where wrangler
   ran). A `.dockerignore` at the repo root would not help: the build
   context is the staged `.build-ctx-gpu/` ([gpu-workers.md](../gpu-workers.md)
   §1). The image needs only `deploy/vast-worker.sh` (the onstart command),
   so copy just that file.
3. Build and push the GPU image as tag `2026-10-06`, the tag
   `coordinator.IMAGE` names (not `$(date +%F)` unless `IMAGE` changes
   with it), following gpu-workers.md §1.
4. Rebuild and redeploy the web app container
   ([operations.md](../operations.md) → Cloud test deployment), then
   restart the laptop server (`systemctl --user restart drum-transcribe`).
5. Delete the older `drum-transcribe-gpu` tags on GHCR (2026-10-03 and
   earlier). They hold the location file, and their worker expects the key.
6. `ls -d output/*/*/stems/htdemucs/*/ | grep -v /source/` and
   `ls -d output/*/* | grep -vE '^output/[a-z0-9-]+/[a-z0-9-]+$'`: anything
   listed loses players or disappears from the pages. Tell the user.

## Verification

- `podman run --rm --entrypoint find ghcr.io/akaihola/drum-transcribe-gpu:2026-10-06 /app -name '.wrangler*'`
  prints nothing.
- GHCR lists no `drum-transcribe-gpu` tags but `2026-10-06` and `latest`.
- One real song processed on the cloud web app finishes, and Vast's record
  of that rental (`, vastai show instance <id> --raw`, while it runs) has
  `LINKS` in its env and no `S3_ACCESS_KEY`/`S3_SECRET_KEY`. This also
  proves the curl worker against Scaleway (task [11] step 6).

Then move [16] to Completed with `[ ]` and start task [15].

## Deployment plan and progress, 2026-10-14

- Move task [16] to In Progress and commit the tracker on the feature branch.
- Copy only `deploy/vast-worker.sh` into the GPU image. Stage only the
  Dockerfile and worker script from `deploy/`, and use tag `2026-10-06`.
- Review and merge the fix into gogo main, without pushing source to GitHub.
- On atom, fast-forward from gogo, run the repository checks, build and push
  the GPU image, verify it contains no Wrangler cache, redeploy the cloud
  web app, restart the laptop service, and remove the old GHCR versions.
- Check atom's output names and report anything hidden by the new rules.
- After deployment, process one real song and inspect its running rental's
  environment for `LINKS` and the absence of bucket credentials. Complete
  [16] awaiting acceptance and start [15] only after these checks pass.

Atom is reachable, but SSH to `akaihola@atom` rejects the available keys
with `Permission denied (publickey,password,keyboard-interactive)`.
Deployment, atom-side checks, registry cleanup, output-name inspection and
real-song verification are pending access. No cloud GPU job has been started.

The fix and build instructions were merged into gogo main without a GitHub
push. Local validation passed: `bash -n deploy/vast-worker.sh`,
`git diff --check`, and static assertions that the Dockerfile copies only
`deploy/vast-worker.sh` from `deploy/`, the staging instructions exclude
other deployment files, and the documented tag matches `coordinator.IMAGE`.
The image has not been built or deployed; the static checks do not replace
atom-side verification. Task [16] stays In Progress and [15] stays queued.
The feature worktree is retained until deployment can finish.

## Deployment, 2026-10-15 (on atom)

- Step 1: atom's main had one commit gogo lacked (99fdf75, the /files/
  XSS handoff file, also on GitHub's main). gogo main has the same file
  byte for byte, so atom's main was moved onto gogo main
  (`git reset --keep`); nothing was lost.
- Checks on atom pass: files-sandbox, gpu-jobs (16 of 16), hostile-names,
  `bash -n deploy/vast-worker.sh`.
- Step 3: built `drum-transcribe-gpu:2026-10-06` (also `latest`) from the
  staged context and pushed both. In the image, `find /app -name
  '.wrangler*'` prints nothing, there is no `cf.json` or `.secrets*`
  anywhere, `/app/deploy` holds only `vast-worker.sh`, and all ten
  checkpoints are there. Pushing needed a new classic GitHub token
  (write:packages, delete:packages): the 2026-09-20 one was saved nowhere.
- Step 4: web app image rebuilt and pushed, container redeployed (ready
  2026-10-15 15:49 UTC); laptop server restarted, listening on
  0.0.0.0:8765.
- Step 5: deleted all ten older GHCR versions: tags `2026-10-03`,
  `cu128-v1`, `dummy` and seven untagged ones, all from 2026-10-03 or
  earlier. GHCR now lists only `2026-10-06` and `latest`.
- Step 6: both `ls` commands list nothing on atom; no song loses players
  or disappears.
- Real song: `taustanauha`'s recording uploaded to the cloud site as
  `dancing-through-life/gpu-check`, GPU box ticked. Vast's record of all
  five rentals (56118859, 56120136, 56120391, 56121670, 56122555) showed
  image `2026-10-06`, env `CLAIM CONTAINER_RUNTIME DEADLINE GENERATION
  LINKS RAW_BARS SONG VARIANTS VERSION`, and no `S3_ACCESS_KEY` or
  `S3_SECRET_KEY` (nor in `onstart`). The job still failed ("5 cloud GPUs
  failed in a row") before any worker started:
  - 1: deleted at 16:00:12 by our own deletion guard (Vast's scheduler,
    IP 13.216.37.47), 11 min into loading and 19 min before its
    deadline; see below.
  - 2, 3, 4: outbid while loading ("meant to be stopped").
  - 5 (fixed price): the host kept retrying one image layer and missed
    the 15-minute start limit. The same layer downloaded fine to atom,
    anonymously, with the right digest.
- Still open then: one real song that finishes, which also proves the curl
  worker against Scaleway. Next: "Try again" just after a full hour.

### The deletion guard fires an hour early (found 2026-10-15, not fixed here)

`vast.add_guard` starts the hourly DELETE 1 s past the first full hour
after the deadline. Vast's scheduler ticks a few seconds after minute 0
(16:00:12 here) and runs a job whose start is less than an hour away, so
the guard with start 17:00:01 ran at 16:00:12. The 2026-10-03 probes fit
this too (gpu-resilience-handoff.md: starts 12:15, 12:35 and 13:22 all ran
at 13:00:29). So every rental whose 30-minute window crosses a full hour
is deleted at that hour, healthy or not. Starting the guard half past the
next full hour instead (+1800 s, not +1 s) fires it at the intended hour
under either reading. Needs its own task.

### Real song finished, 2026-10-15 20:27–20:33 UTC

"Try again" on `dancing-through-life/gpu-check`, pressed just after
20:27 UTC so the early guard could not fire. Rental 56149713 (CN host,
the same machine as attempts 3 and 4, image already cached) was running
66 s after renting. While it ran, Vast's record showed image
`2026-10-06`, `LINKS` in its env and no `S3_ACCESS_KEY`/`S3_SECRET_KEY`.
adtof, mdx23c and fused were ready by 20:33:28 (829, 1564 and 829
events); the drums stem, the drumless backing and every variant's files
open on the cloud site. The worker deleted its own rental at 20:32:45
(Vast audit log: from the host's address) and the coordinator removed
its guard. This proves the curl worker against Scaleway (task [11]
step 6). All steps and checks of this task are done.
