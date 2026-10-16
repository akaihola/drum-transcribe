# Stop the deletion guard deleting rentals an hour early

Found 2026-10-15 while deploying task [16] (its description, "The
deletion guard fires an hour early", has the evidence).

Every rental gets a guard: a job on Vast's own servers that deletes the
machine in case both the web app and the machine's worker fail to.
`vast.add_guard` starts it 1 s past the first full hour after the
rental's deadline. Vast runs such a job at the first hourly tick (a few
seconds past minute 0) at which its start is less than an hour away. So
a rental whose 30-minute window crosses a full hour is deleted at that
hour, while still loading or working: rental 56118859's guard (start
17:00:01 UTC) deleted it at 16:00:12, 19 minutes before its deadline.
That hits about half of all rentals, each time wasting an attempt and
its loading time.

Fix: start the guard half past the next full hour (+1800 s, not +1 s).
That fires it at the intended full hour under both readings of Vast's
scheduler; the 2026-10-03 probes in gpu-resilience-handoff.md fit both.
Update the `add_guard` docstring, gpu-workers.md (the guard paragraph)
and gpu-resilience-handoff.md (Guard timing).

Verification: a rental claimed in the second half of an hour keeps
running past the full hour, and Vast's audit log shows the guard's
DELETE (IP 13.216.37.47) only after the deadline.

2026-10-16, task [8]'s checks: three more. Rentals 56272851, 56272984
and 56273095 (claimed 16:53–16:55 UTC, deadlines 17:22–17:25, guards
starting 18:00:01) were deleted by Vast's scheduler at 17:00:08–09 UTC
(IP 13.216.37.47), one of them while its worker ran. Rentals claimed
before half past were never hit.
