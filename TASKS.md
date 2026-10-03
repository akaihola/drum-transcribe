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

- [5] Block network scanners
  <!-- hai:{"id":"simple-d9594726c5ac8fca","updatedAt":"2026-10-03T17:40:05.628Z"} -->

- [8] Cloud GPU checks on real rentals
  <!-- hai:{"id":"simple-6497f32cbc441249","updatedAt":"2026-10-03T17:41:23.086Z"} -->

## Scheduled

- [4] Compress player nodes UI
  <!-- hai:{"id":"simple-0082f116ae303884","updatedAt":"2026-10-03T17:39:46.164Z"} -->

## In Progress

## Completed / Accepted

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

<!-- hai:reserved-numbers:1,2,3,4,5,6,7,8,9 -->

[2]: docs/tasks/2-pdf-export.md

[3]: docs/tasks/3-check-need-for-firewall-rule.md

[4]: docs/tasks/4-compress-player-nodes-ui.md

[5]: docs/tasks/5-block-network-scanners.md

[6]: docs/tasks/6-measure-recording-alignment.md

[7]: docs/tasks/7-verify-recording.md

[8]: docs/tasks/8-cloud-gpu-checks-on-real-rentals.md

[9]: docs/tasks/9-robust-gpu-jobs.md

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
