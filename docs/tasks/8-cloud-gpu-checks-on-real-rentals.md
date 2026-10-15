---
depends_on: [16]
---
# Cloud GPU checks on real rentals

Run the cloud GPU checks not yet done on real rentals: coordinator killed
between claim, create and guard; restart mid-upload and mid-conversion; a
host's bucket route blocked with `iptables`; a failing worker DELETE after
its done markers; a fixed-price fifth try. See
[verification results](../gpu-resilience-handoff.md#verification-results-2026-10-03).

Rentals wait for task [16]: until its fix is deployed, a rented machine
gets the results-bucket key.

## Plan (2026-10-15, on atom)

The crash points last milliseconds, so the checks can't be run by
redeploying the cloud web app. `checks/gpu-rentals.py` runs the real web
app and coordinator on atom instead, against real Vast.ai rentals and the
real GPU image, and kills itself at a chosen point. To keep it apart from
the cloud web app, it uses:

- its own two buckets, `drum-transcribe-check-jobs` and
  `drum-transcribe-check-results`, made for these checks and deleted after,
  with the cloud web app's two keys;
- its own rental label, `drum-transcribe-check/`: the cloud web app's
  sweep destroys only instances labelled `drum-transcribe/`, and this one
  leaves those alone;
- an empty output folder at every start, like a new container.

A short song, uploaded through the app's own upload request. For each
check, note the instance ids, and afterwards confirm with
`, vastai show instances` and the scheduled jobs that nothing is left.

1. Kill the app after the claim is saved, after Vast creates the rental,
   and before and after the deletion guard is set up. After a restart:
   one rental per job, found by label or (no create sent) ruled out by the
   audit log after 10 minutes; one guard each; caps unchanged.
2. Kill it mid-upload: nothing is accepted, no record, nothing under
   `sources/`. Kill it while ffmpeg takes the audio out of a video: after
   the restart the job prepares again from the stored original and
   finishes once, on the rental it already had.
3. Block or throttle the host's route to the bucket with `iptables` over
   ssh: the transfer and the attempt end within their limits, the rental
   ends as "slow bucket link" and its site is blocklisted.
4. Make the worker's own DELETE fail (`console.vast.ai` unreachable on the
   host) after its done markers: the app ends the rental, and keeps its
   guard until Vast stops listing it.
5. Bid tries 1–4 below the market without `cancel_unavail`, so Vast
   parks each as stopped; the fifth try rents at the fixed price.

Record results under the handoff's "Verification results" section.

## Status, 2026-10-15 13:30: waiting for [16]

Not run; no rental, bucket or Vast change made. Task [16] built both
images on atom (`drum-transcribe-gpu:2026-10-06`, `webapp:test`) but
stopped before pushing them: GHCR has no `2026-10-06` tag, the web app in
Scaleway's registry and its container are from 2026-10-05, and `main` (atom
and gogo) still lists [16] In Progress. The coordinator rents
`IMAGE` = `2026-10-06`, so rentals couldn't even load before the push.

Ready: `checks/gpu-rentals.py` (starts in cloud mode on atom and reads the
check jobs bucket, not the live one: smoke-tested without buckets), a
60-s test clip (MP3, and PCM in MKV for the conversion check). Vast credit
$8.85, no instances. The ssh key registered with Vast is atom's
`~/.ssh/id_ed25519` (not `.secrets.gpu-ssh`). Untested: ssh into a rental
with it, and whether a Vast container may use `iptables`.
