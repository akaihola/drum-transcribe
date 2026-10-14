# Malicious GPU hosts can corrupt data

Fix this security issue:

**Every rented GPU machine gets the key to the whole results bucket.** `coordinator.py:441-449` sends it to third-party Vast hosts, whose operators can read it. It can read, write and delete everything, and the web app uses the same key. A malicious host can therefore:
- plant names and files that the pages insert without escaping (`serve.py:634-636`, `serve.py:1020-1035`, `mobile.js:289-292`), which is a second XSS route;
- fake "done" markers that end other people's jobs (`coordinator.py:232-257`);
- fake or delete the anonymous-limit markers;
- delete all results.

(Line numbers refer to commit 34d262f.)

## Confirmed

- The key reaches the hosts as `S3_ACCESS_KEY`/`S3_SECRET_KEY` in the Vast instance's environment (`Coordinator.payload`). It is the same key that `gate.results_bucket()` uses for the web app. The job records are safe: they sit in the separate `drum-transcribe-jobs` bucket, whose key never leaves the web app.
- The names route was reproduced on 2026-10-05 (XSS fix review on atom). A project directory named `<img src=x onerror=…>` and a file named `source."><img src=x onerror=…>` both ran script in Chromium on `/` and `/p/<song>`. `coordinator.collect` and `deploy/sync_bucket.py` only check that a path stays inside the output root. `scan_output` passes names through as they are (`p.name`, `v.name`, the `source.*` glob, the `stems/htdemucs/*/` glob), and the templates paste them into `innerHTML`.
- Not the same as the other XSS: hostile file *contents* served from `/files/` are already handled by that fix (`nosniff` + `Content-Security-Policy: sandbox; default-src 'none'`). This task is about the key and about *names* reaching the app's own pages.

## Fix, in two parts

1. **Narrow what a host can do; this closes all four routes.** A host should be able to read only its own job's recording and write only its own job's results, under the names the app expects. One way: the coordinator gives each rental time-limited presigned URLs (GET for `sources/<job>/source.<ext>`, PUT for each expected result file) instead of a key, and `deploy/vast-worker.sh` uploads with them instead of rclone. Another way: hosts write only to a staging prefix, and the coordinator checks names against an allowlist before copying results into place. Done markers must come from somewhere a host cannot forge, or be checked by the coordinator. The anonymous-limit markers must be out of the hosts' reach.
2. **Backstop on the pages.** `scan_output` should admit only names the app creates itself (project/version dirs matching `[a-z0-9-]+`, `source` plus an extension in `AUDIO_EXTS`, the fixed `stems/htdemucs/source/` paths). Alternatively, every server string interpolated into `innerHTML` should be HTML-escaped, as feedback text already is. Then a bad name that reaches the bucket by some other route still can't run script.

## Checks

- A mocked check, like `checks/gpu-jobs.py`: a host's credentials or URLs cannot write outside its job, cannot write a `done` marker for another job, and cannot touch `created` markers.
- A hostile project, version or file name under the output root renders as text (or is skipped) on `/` and `/p/<song>`, in Chromium.

## Related

- The `[*]` entry for the names half only ("Stop file and folder names from running as script on the pages") was folded into this task on 2026-10-05. Its reproduction is the [high] finding in `docs/files-xss-handoff.md`.

## Done (2026-10-06, agent@gogo; not deployed)

Commits 060d81c, b849212, 2995d10, 0ad2ae7 on main (not pushed: task 12's rule).

- Part 1: hosts get no key. `coordinator._Job.links` publishes
  `sources/<job>/<claim>.links` (presigned GET for the recording under each
  audio ending and the restored files, PUT for `SHARED` + `RESULTS` per variant
  + the rental's log; expire deadline + 10 min) before the claim; env `LINKS`
  holds only the link to the list (~45 links × ~340 chars, too long for env).
  `deploy/vast-worker.sh` uses curl through the links; rclone left the image.
  `coordinator.IMAGE` is now `drum-transcribe-gpu:2026-10-06`.
- Part 2: `scan_output` lists only `[a-z0-9-]+` project/version/variant dirs,
  `source.<letters/digits>`, and stems at `stems/htdemucs/source/`.
- Checks: `checks/gpu-jobs.py` `check_hosts_hold_links_not_the_key` (fails on
  the old coordinator); `checks/hostile-names.py` (Chromium ran the planted
  script on the old code, `window.pwned=5` on `/`; none now). The worker ran
  end to end against a local moto S3 with real boto3 SigV4 links (moto does not
  verify signatures). Not yet run on a real rental or real Scaleway.

Still to do, on atom:
1. Bring the commits to atom's clone without GitHub.
2. Fix task 12's image-context issue first, then build and push the GPU image
   as tag `2026-10-06` (TAG=2026-10-06, not `$(date +%F)` unless IMAGE is
   changed to match). It must exist before the web app is redeployed.
3. Redeploy the web app container; restart the laptop server.
4. Replace the worker S3 key, which every earlier rental's host saw:
   task [15] (`docs/tasks/15-replace-the-bucket-key.md`).
5. `ls -d output/*/*/stems/htdemucs/*/ | grep -v /source/` and
   `ls -d output/*/* | grep -vE '^output/[a-z0-9-]+/[a-z0-9-]+$'`: anything
   listed loses players or disappears from the pages.
6. One real cloud GPU job (task 8) to prove the curl worker against Scaleway.

2026-10-10: steps 1–3, 5 and 6 are now task [16]; step 4 stays task [15].
