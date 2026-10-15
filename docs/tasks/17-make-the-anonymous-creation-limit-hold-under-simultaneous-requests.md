From task [12]. The cloud web app lets anonymous visitors create only a limited number of versions, but sending several requests at the same moment gets around it: `gate.allow_anonymous()` is checked when a request starts (`serve.py:1962`), while `gate.write_marker()` records the creation only at the end (`serve.py:1744` for links, `serve.py:1936` for uploads). In a local test 5 parallel anonymous uploads all succeeded; with the cloud GPU on, each is a paid rental.

## Fix

Reserve the anonymous slot atomically before any slow work (e.g. one process-wide lock around check-and-mark, or an exclusive-create marker written at check time and removed if creation fails), so the check and the marker cannot interleave.

## Verification

Fire 5 simultaneous anonymous creations at a local `serve` with the gate on: only the allowed number succeed, the rest get 429 `throttled`. A failed creation (bad link → 400) still spends no slot. Unlocked visitors are not limited.