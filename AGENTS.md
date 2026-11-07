# Agent entrypoint (keep context small)

**Smart Retention Offers**: two custom services (inference/experiment planning; analytics/Grafana), one external ML researcher. Never train a churn model or invent discount uplift/savings.

## Role routing
- **Lead/main**: read `.workflow/roles/lead.md`, `.workflow/README.md`, active milestone only.
- **Backend worktree**: read `services/inference/AGENTS.md`, assigned `.workflow/jobs/<ID>.md`.
- **Analytics worktree**: read `services/analytics/AGENTS.md`, assigned job.
- **QA worktree**: read `tests/AGENTS.md`, assigned job.

## Non-negotiable rules
- `main` owns planning and frozen contracts; `develop` is the test/integration branch.
- Job worktrees fork from `develop`; workers commit only on task branches.
- Lead merges into `develop`, gates the exact SHA, then promotes only that SHA into `main`.
- QA writes tests from contracts in parallel with developers; gate failures create NEW FIX jobs.
- Existing churn probabilities are inputs from external ML or deterministic mocks; no scoring formulas here.
- No observed treatment effect in seed data: discounts are hypothetical tests, not optimized savings.
- Use UTC, pseudonymous user IDs, read-only Grafana DB access, no unsafe model deserialization.
- Never bulk-read unrelated role files: each worker gets local instructions only.
