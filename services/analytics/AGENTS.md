# Analytics Agent — Storage + Grafana

Read only your assigned `.workflow/jobs/<ID>.md`, this folder, `postgres/` and `grafana/` as needed.

**Own** `services/analytics/`, `postgres/`, `grafana/`. No ML scoring or uplift. Persist immutable model predictions and experiment proposal snapshots, store actual observations separately; reject conflicting IDs, support idempotent retries, UTC and correct SQL aggregations. Grafana must distinguish mock churn risk, break-even thresholds, budget exposure, and observed outcomes. Never show hypothetical savings as actual. Commit in assigned worktree.
