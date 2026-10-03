# Issue tracking for drum-transcribe

Rules for TASKS.md usage are at the bottom of the file. The format and workflow
come from Filemill's TASKS.md.

Current task status lives here. [The roadmap](docs/roadmap.md) and handoff
documents provide background; their historical plans do not set task status.

## Unverified proposals

- [*] Decide the scope of feedback-driven correction: apply per-note fixes to
  scores, or tune detector thresholds using corrections. Resolve how feedback
  maps to hits when regeneration changes notation.
  See [the proposal](docs/roadmap.md#agreed--floated-next-steps).

- [*] Add PDF export if printed parts are wanted.
  See [the proposal](docs/roadmap.md#agreed--floated-next-steps).

- [*] Confirm whether port 8765 still needs a permanent firewall opening.
  This is work for the user. See [operations](docs/operations.md).

## Ordered backlog

- [*] Block obvious scanner paths such as `/.env*` and `/.git/*` with a
  Cloudflare WAF rule so probes do not wake the cloud container.
  See [the agreed next step](docs/roadmap.md#agreed--floated-next-steps).

- [*] Measure local recording alignment with real wired hardware against the
  10 ms target. Check microphone processing settings and count-in timing before
  deciding whether automatic click calibration is needed. Requires the user's
  recording equipment. See [recording validation](docs/local-recording-handoff.md#implementation-results).

- [*] Verify recording on the cloud site and phones, including mobile memory
  use, WAV export, background operation and screen lock.
  See [recording validation](docs/local-recording-handoff.md#implementation-results).

- [*] Run the cloud GPU checks not yet done on real rentals: coordinator
  killed between claim, create and guard; restart mid-upload and
  mid-conversion; a host's bucket route blocked with `iptables`; a failing
  worker DELETE after its done markers; a fixed-price fifth try.
  See [verification results](docs/gpu-resilience-handoff.md#verification-results-2026-10-03).

## Scheduled

- [*] Make backing selection respond immediately and show audio loading progress.

## In Progress

## Completed / Accepted

- [ ] [*] Make cloud GPU jobs survive closed pages, failed hosts and container
  restarts, without duplicate rentals (job records, one coordinator, baked
  worker, deletion guards). See [the handoff](docs/gpu-resilience-handoff.md#implementation-2026-10-03).

- [ ] [*] Adopt Filemill's TASKS.md convention, link it from AGENTS.md and the
  roadmap, and seed it with this project's outstanding work.

[*]: TASKS.md

---

## Rules

Here are the rules for TASKS.md usage:

### TASKS.md maintenance sessions

- In `## Completed / Accepted`, `- [ ] [N] summary` or `- [ ] [*] summary`
  means completed work awaiting user acceptance. `- [x] [N] summary` or
  `- [x] [*] summary` means the user has accepted it. Only user acceptance
  changes `[ ]` to `[x]`; completion, tests and deployment do not.
- Move newly completed issues into `## Completed / Accepted` with `[ ]`.
- During the next maintenance run, remove only `[x]` issues from this section,
  plus their unused description files and reference-style links. Keep `[ ]`
  issues and any files or links still referenced by another issue.
- Each issue must retain either
    - a numbered reference-style link such as `[1]` to a description file, or
    - `[*]` to indicate no description file is needed for a simple task.
- `[~]` marks an issue that is actively in progress. Keep its `[N]` or `[*]`
  identifier, for example `- [~] [*] summary`. When the issue is complete,
  move it to `## Completed / Accepted` with `[ ]`, pending user acceptance.
- Link references are listed between `## Completed / Accepted` and `## Rules`.
- Keep summaries concise. Move detailed requirements, rationale, examples and acceptance
  criteria into `docs/tasks/N-issue-description.md`; preserve simple tasks inline. Reuse
  an existing description for the same issue.
- For a new description, use the first unused number, checking both this file and
  description filenames in Git history. Do not reuse numbers of accepted issues.
- The section records work status; the checkbox in `## Completed / Accepted` records
  user acceptance. Completed descriptions retain historical
  requirements, paths and validation results; they are not current implementation
  instructions. Date later corrections and distinguish regressions from earlier work.
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
- When you move an issue, preserve its identifier, text and line wrapping.
  Change only the status checkbox when completion or user acceptance requires it.
  This keeps moves identifiable in Git and reduces avoidable conflicts.

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
- Move the issue from `## In Progress` to `## Completed / Accepted` in `TASKS.md@main` with `[ ]`,
  pending user acceptance, and commit.
- Do any deployment steps if defined in the general development workflow.
