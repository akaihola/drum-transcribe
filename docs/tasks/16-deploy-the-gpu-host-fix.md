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
