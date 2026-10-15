# Issue tracking for drum-transcribe

Rules for TASKS.md usage are at the bottom of the file. The format and workflow come
from Filemill's TASKS.md.

Current task status lives here. [The roadmap](docs/roadmap.md) and handoff documents
provide background; their historical plans do not set task status.

## Unverified proposals

- [7] Verify recording
  <!-- hai:{"id":"simple-b4eb55961f8ad9a7","updatedAt":"2026-10-03T17:40:57.897Z"} -->

- [6] Measure recording alignment
  <!-- hai:{"id":"simple-12ed7b4195ff20ff","updatedAt":"2026-10-03T17:40:41.277Z"} -->

- [1] Decide scope of feedback-driven correction
  <!-- hai:{"id":"simple-1847537fd7ed7448","updatedAt":"2026-10-03T17:38:43.030Z"} -->

- [2] PDF export
  <!-- hai:{"id":"simple-db8f0589550798ee","updatedAt":"2026-10-03T17:38:59.302Z"} -->

- [3] Check need for firewall rule
  <!-- hai:{"id":"simple-c856aacf0be13947","updatedAt":"2026-10-03T17:39:20.353Z"} -->

## Ordered backlog

- [15] Replace the results-bucket key
  - Depends on: [16]

- [17] Make the anonymous creation limit hold under simultaneous requests
  <!-- hai:{"id":"simple-38df422a-9696-4960-99ea-f78653b9f3f2","createdAt":"2026-10-14T21:22:03.112Z","updatedAt":"2026-10-14T21:22:03.112Z"} -->

- [18] Close the remaining private-network fetch gaps
  <!-- hai:{"id":"simple-21bf943a-28fc-4bd0-8994-5707027a042a","createdAt":"2026-10-14T21:22:03.430Z","updatedAt":"2026-10-14T21:22:03.430Z"} -->

- [19] Stop publishing uploaders' private metadata
  <!-- hai:{"id":"simple-4a744b57-a13a-4223-b112-09332d14b32c","createdAt":"2026-10-14T21:22:03.748Z","updatedAt":"2026-10-14T21:22:03.748Z"} -->

- [20] Stop a link with a line break from breaking the song list
  <!-- hai:{"id":"simple-53e050da-a8bd-47c5-b5a9-99c19bacb4cc","createdAt":"2026-10-14T21:22:04.129Z","updatedAt":"2026-10-14T21:22:04.129Z"} -->

- [13] Queue fixing low priority security issues
  <!-- hai:{"id":"simple-edb26053-520e-4bbc-bac4-21dd9ba41e6e","priority":"none","labels":[],"createdAt":"2026-10-05T18:51:26.504Z","updatedAt":"2026-10-05T18:51:26.504Z"} -->

- [14] Queue fixing low priority PII issues etc
  <!-- hai:{"id":"simple-202c2bed-255f-4da9-a3ac-c0b1e0f9abfb","priority":"none","labels":[],"createdAt":"2026-10-05T18:55:01.490Z","updatedAt":"2026-10-05T18:55:25.921Z"} -->

- [21] Purge security task notes from Git history, then push
    - Depends on: [13], [14], [15], [16], [17], [18], [19], [20]
  <!-- hai:{"id":"simple-6572fd80-2f1d-40a1-bbdf-e1d2426e22a7","createdAt":"2026-10-14T21:22:04.438Z","updatedAt":"2026-10-14T21:22:12.711Z"} -->

## Scheduled

- [8] Cloud GPU checks on real rentals
  <!-- hai:{"id":"simple-6497f32cbc441249","updatedAt":"2026-10-14T21:18:30.018Z"} -->

## In Progress

- [~] [16] Deploy the GPU host fix (no cloud GPU jobs until then)
  - Depends on: [11]
  <!-- hai:{"updatedAt":"2026-10-14T20:44:17.403Z"} -->

## Completed / Accepted

- [ ] [12] Queue medium level security issues
  <!-- hai:{"id":"simple-cdf92e3d-8a75-4367-8a79-dd5652c55f7b","priority":"none","labels":[],"createdAt":"2026-10-05T18:48:52.458Z","updatedAt":"2026-10-14T21:22:21.458Z"} -->

- [x] [5] Block network scanners
  <!-- hai:{"id":"simple-d9594726c5ac8fca","updatedAt":"2026-10-07T04:05:06.729Z"} -->

- [ ] [11] Malicious GPU hosts can corrupt data
  <!-- hai:{"id":"simple-590d8bef-9a9c-4925-a17c-f66e0e83a827","priority":"none","labels":[],"createdAt":"2026-10-05T18:44:04.871Z","updatedAt":"2026-10-05T18:44:04.871Z"} -->

- [ ] [*] Stop links from planting web pages on the site (stored XSS): save
      downloads as `fetched.bin`, send only real YouTube/Drive links to
      yt-dlp/gdown, delete downloads after conversion, sandbox `/files/`.
      MP3/AAC/Opus links keep their audio as it is (FLAC only for the rest).

- [x] [10] Use compact tree and sideways player layouts
  - Depends on: [4]
  <!-- hai:{"updatedAt":"2026-10-04T21:50:32.789Z"} -->

- [x] [4] Compress player nodes UI
  <!-- hai:{"id":"simple-0082f116ae303884","updatedAt":"2026-10-03T17:39:46.164Z"} -->

- [x] [*] Show backing download percentage in the Loading button's circular indicator.
  <!-- hai:{"id":"simple-8f353ed6b83489a9","updatedAt":"2026-10-03T17:41:33.474Z"} -->

- [x] [*] Make backing selection respond immediately and show audio loading progress.
  <!-- hai:{"id":"simple-4179ed2eade00883","updatedAt":"2026-10-03T17:41:46.978Z"} -->

- [x] [9] Robust GPU jobs
  <!-- hai:{"id":"simple-d8c0e35b43a17e77","updatedAt":"2026-10-03T17:42:31.492Z"} -->

- [x] [*] Adopt Filemill's TASKS.md convention, link it from AGENTS.md and the roadmap,
      and seed it with this project's outstanding work.
  <!-- hai:{"id":"simple-14d12577ba3cdc94","updatedAt":"2026-10-03T17:42:36.974Z"} -->

[*]: TASKS.md

---

[1]: docs/tasks/1-decide-scope-of-feedback-driven-correction.md

<!-- hai:reserved-numbers:1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21 -->

[2]: docs/tasks/2-pdf-export.md

[3]: docs/tasks/3-check-need-for-firewall-rule.md

[4]: docs/tasks/4-compress-player-nodes-ui.md

[5]: docs/tasks/5-block-network-scanners.md

[6]: docs/tasks/6-measure-recording-alignment.md

[7]: docs/tasks/7-verify-recording.md

[8]: docs/tasks/8-cloud-gpu-checks-on-real-rentals.md

[9]: docs/tasks/9-robust-gpu-jobs.md

[10]: docs/tasks/10-responsive-player-layouts.md

[11]: docs/tasks/11-malicious-gpu-hosts-can-corrupt-data.md

[12]: docs/tasks/12-queue-medium-level-security-issues.md

[13]: docs/tasks/13-queue-fixing-low-priority-security-issues.md

[14]: docs/tasks/14-queue-fixing-low-priority-security-issues.md

[15]: docs/tasks/15-replace-the-bucket-key.md

[16]: docs/tasks/16-deploy-the-gpu-host-fix.md

[17]: docs/tasks/17-make-the-anonymous-creation-limit-hold-under-simultaneous-requests.md

[18]: docs/tasks/18-close-the-remaining-private-network-fetch-gaps.md

[19]: docs/tasks/19-stop-publishing-uploaders-private-metadata.md

[20]: docs/tasks/20-stop-a-link-with-a-line-break-from-breaking-the-song-list.md

[21]: docs/tasks/21-purge-security-task-notes-from-git-history-then-push.md

## Rules

Here are the rules for TASKS.md usage:

### TASKS.md maintenance sessions

- In `## Completed / Accepted`, `- [ ] [N] summary` or `- [ ] [*] summary` means
  completed work awaiting user acceptance. `- [x] [N] summary` or `- [x] [*] summary`
  means the user has accepted it. Only user acceptance changes `[ ]` to `[x]`;
  completion, tests and deployment do not.
- Move newly completed issues into `## Completed / Accepted` with `[ ]`.
- During the next maintenance run, remove only `[x]` issues from this section, plus
  their unused description files and reference-style links. Keep `[ ]` issues and any
  files or links still referenced by another issue.
- Each issue must retain either
  - a numbered reference-style link such as `[1]` to a description file, or
  - `[*]` to indicate no description file is needed for a simple task.
- `[~]` marks an issue that is actively in progress. Keep its `[N]` or `[*]` identifier,
  for example `- [~] [*] summary`. When the issue is complete, move it to
  `## Completed / Accepted` with `[ ]`, pending user acceptance.
- Link references are listed between `## Completed / Accepted` and `## Rules`.
- Keep summaries concise. Move detailed requirements, rationale, examples and acceptance
  criteria into `docs/tasks/N-issue-description.md`; preserve simple tasks inline. Reuse
  an existing description for the same issue.
- For a new description, use the first unused number, checking both this file and
  description filenames in Git history. Do not reuse numbers of accepted issues.
- The section records work status; the checkbox in `## Completed / Accepted` records
  user acceptance. Completed descriptions retain historical requirements, paths and
  validation results; they are not current implementation instructions. Date later
  corrections and distinguish regressions from earlier work.
- Any completed tasks which haven't yet been moved from `## In Progress` to
  `## Completed / Accepted` should be moved there.
- Any in progress tasks which haven't yet been moved from `## Ordered backlog` or
  `## Scheduled` to `## In Progress` should be moved there.
- Ensure there are no duplicate sections, and that they are in the correct order:
  `## Unverified proposals` -> `## Ordered backlog` -> `## Scheduled` ->
  `## In Progress` -> `## Completed / Accepted` -> `## Rules`.

### Modifying issues

- Ensure dependencies between issues are correctly updated.
- State dependencies using
  - indented `- Depends on: [N]` bullets in TASKS.md, and
  - YAML frontmatter in description files.
- Ensure backlog order respects dependencies.
- When you move an issue, preserve its identifier, text and line wrapping. Change only
  the status checkbox when completion or user acceptance requires it. This keeps moves
  identifiable in Git and reduces avoidable conflicts.

### Workflow for new issue completion

Below, `<filename>@<branch>` means you must operate on the file in the specified branch.

1. Choose an issue and schedule work.

- Pick a backlog issue from `TASKS.md@main`. Pick the first issue that has no dependency
  on any uncompleted issue.
- Move it under `## Scheduled` in `TASKS.md@main` and remove it from
  `## Ordered backlog` and commit `main`.

2. Work on the issue.

- Move the issue under `## In Progress` in `TASKS.md@<worktree-branch>`, ensure no copy
  is left in `## Ordered backlog` or `## Scheduled`.
- Create or update, review and refine a plan in
  `docs/tasks/<N-issue-description>.md@<worktree-branch>`, if more description is needed
  than nicely fits in a bullet point. If you created a plan document, link to it using a
  new `[N]` reference-style link.
- If needed, reword the issue in `TASKS.md@<worktree-branch>` to be more accurate.
- Commit the description file, if any, and `TASKS.md@<worktree-branch>`.
- Implement the plan, and lint, test, review and refine the implementation in the
  worktree feature branch.

3. Merge and deploy.

- Rebase the worktree feature branch on `main` and resolve any conflicts.
- Merge the rebased branch on `main`, and remove the worktree and branch.
- Move the issue from `## In Progress` to `## Completed / Accepted` in `TASKS.md@main`
  with `[ ]`, pending user acceptance, and commit.
- Do any deployment steps if defined in the general development workflow.
