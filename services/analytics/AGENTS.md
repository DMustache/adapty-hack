# Analytics Agent — Storage and API

Read only your assigned `.workflow/jobs/<ID>.md`, this folder and `postgres/` as needed.

**Own** `services/analytics/` and `postgres/`. No ML scoring or uplift. Persist immutable model predictions and experiment proposal snapshots, store actual observations separately; reject conflicting IDs, support idempotent retries, UTC and correct SQL aggregations. Expose the stored data needed by Grafana through agreed database tables. Request dashboard changes from Lead; do not edit `grafana/`. Commit in assigned worktree.
