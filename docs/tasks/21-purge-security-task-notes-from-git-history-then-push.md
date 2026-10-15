---
depends-on: [13, 14, 15, 16, 17, 18, 19, 20]
---

From task [12]: no descriptions of security holes may reach the public GitHub repository.

State on 2026-10-15: GitHub (`origin`) has none of them; `origin/main` and local `main` have diverged. Local `main` (gogo, and atom once pulled from gogo) does contain them: the tracker automation committed `TASKS.md` entries and `docs/tasks/11-16-*.md` from commit `dde23b6` (2026-10-14) onwards; earlier `docs/files-xss-handoff.md` too if present. Already public and acceptable to leave: `docs/webapp.md`'s note on DNS rebinding (commit `40376e5`), which task [18] rewrites once the gap is closed.

## Steps (only after every security task listed under Depends on is fixed, and the fix tasks queued by [13] and [14] too)

1. Remove the security issues from `TASKS.md` and their files from `docs/tasks/` (or reword them so they no longer describe open holes).
2. Rewrite local history so no commit contains them (`git filter-repo` on a fresh clone, or an interactive-free rebase that drops/edits the tracker-only commits); check with `git log -p --all | grep -iE '<key phrases>'`.
3. Reconcile with `origin/main` (rebase onto it), have atom's clone re-fetch from gogo, delete stale local branches/worktrees holding the old commits.
4. Push; force-push only if something security-related had reached GitHub after all.

User confirms before the push.