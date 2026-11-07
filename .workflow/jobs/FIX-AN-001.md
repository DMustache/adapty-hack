---
id: FIX-AN-001
milestone: M0
role: analytics
status: READY
depends_on: []
owned_paths:
  - services/analytics/app/main.py
---
# FIX-AN-001: Correct optional app filter SQL

## Failure
After M0 Compose startup, `python scripts/smoke_demo.py` reached `GET /v1/metrics/churn-risk?app_id=lumen-demo` and received HTTP 500. Analytics logs show `psycopg.errors.IndeterminateDatatype: could not determine data type of parameter $1`. Expected: risk points for an app or all apps. Actual: query `WHERE (%s IS NULL OR app_id=%s)` leaves a bind parameter untyped. M0 gate log: `.worktrees/develop/.agent-runtime/gates/M0.log`; reproduced after startup at commit `ec8e653`.

## Work
Change only the churn-risk query to use explicit SQL branches for filtered and unfiltered reads, with bound parameters for the filter. Preserve ordering and response shape. Do not edit contracts or shared files.

## Acceptance and handoff
Both filtered and unfiltered requests return points without SQL errors; the M0 HTTP smoke passes after integration. Run targeted checks. Commit on the fix branch and write `handoffs/FIX-AN-001.md` with commit SHA, tests, and any blocker.
