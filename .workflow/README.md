# Lead-managed workflow

## Branch invariants

| Branch/worktree | Owner | Purpose | Allowed changes |
|---|---|---|---|
| `main` | Lead | plans, milestones, contracts, approved baseline | `.workflow/`, `contracts/`, shared docs after gate |
| `develop` | Lead as integrator | integrated code, QA gate | merges only; no worker direct commits |
| `task/<JOB-ID>` | assigned worker | one job, one worktree | owned source files, job-specific handoff |
| `fix/<JOB-ID>` | assigned worker | failed-gate repair | limited bug fix and regression tests |

### Planning lifecycle
1. Lead checks current milestone and inspects code baseline.
2. Lead **freezes contracts for the wave** in `main`; creates one job file per independently testable task in `.workflow/jobs/`.
3. Lead commits planning files in `main` and executes `scripts/sync-plan.sh`. This merges planning changes into `develop`, making them visible to new task worktrees.
4. Lead creates worktrees with `scripts/spawn-job.sh <JOB-ID>`; commands return paths and write a gitignored `.agent-runtime/ASSIGNMENT.md`.
5. Developers and QA work in parallel from `develop`. Each commits to its own branch. QA tests are designed from frozen contracts, not current implementation.
6. Lead integrates task branches one at a time via `scripts/integrate-job.sh <JOB-ID>`. QA tests can fail until required implementation branches are all integrated.
7. Lead runs `scripts/gate.sh <MILESTONE>` on `develop` (the script enforces branch/commit checks).
8. On failure: Lead creates `.workflow/jobs/FIX-XXX.md` in `main`, syncs plan, spawns a new `fix/FIX-XXX` branch, delegates, integrates, and reruns gate.
9. On success: Lead promotes **the tested develop SHA** with `scripts/promote-milestone.sh <MILESTONE>` and plans the next wave.

### Why tasks are committed before worktrees spawn
A job created in `main` is *not* automatically visible in a branch forked from `develop`. `sync-plan.sh` explicitly transfers it to `develop` first. Never ask a worker to read an un-synced task file.

### What if contracts need to change mid-wave?
Do not rewrite a frozen contract silently. Lead creates an explicit revision job, commits a versioned schema change in `main`, integrates/synchronizes the change, and only then dispatches dependent work. Existing workers either finish on the old contract or rebase onto the new `develop` under Lead control.

### Conflict handling
Workers do not edit shared files (`contracts/`, `docker-compose.yml`, `.workflow/`). Lead owns those files. For integration conflicts, Lead resolves on `develop` and reruns tests; never claim tests passed on another commit.

### QA gate
- Run unit and contract tests on `develop`.
- Validate Docker Compose and run the actual HTTP mock E2E scenario.
- Save logs under `.agent-runtime/gates/` (local, gitignored).
- A passing gate contains the exact `develop` Git SHA; a later merge invalidates it.

### Defect cycle
Defect job must contain failing command, expected/actual, log or traceback, owner, acceptance criteria, test reference, and parent milestone. QA and developer can independently create regression tests/fixes; Lead controls dispatch. Templates are in `.workflow/templates/`.

### Context budget
Agents read `AGENTS.md`, their scoped `AGENTS.md`, one job and related contract only. Do not bulk-load the entire `.workflow/` tree into each worker's context.
