---
id: FIX-QA-001
milestone: M0
role: qa
status: READY
depends_on: []
owned_paths:
  - tests/
---
# FIX-QA-001: Regression test for optional churn-risk filter

## Failure
M0 smoke found HTTP 500 on `GET /v1/metrics/churn-risk?app_id=lumen-demo`; Analytics logs report `psycopg.errors.IndeterminateDatatype` from the optional filter query. Expected: filtered and unfiltered reads both work. Actual: the nullable bind in the query cannot be typed. Parent milestone M0; log: `.worktrees/develop/.agent-runtime/gates/M0.log` at commit `ec8e653`.

## Work
Add a focused regression test under `tests/` that exercises the analytics risk endpoint for both filter cases and verifies the executed SQL/parameters and response ordering. Use a fake DB cursor if a live DB is unavailable; do not copy implementation logic into the test. Do not modify source or contracts.

## Acceptance and handoff
The test fails against the old query and passes after the analytics fix. Run targeted tests. Commit on the fix branch and write `handoffs/FIX-QA-001.md` with commit SHA, tests, and any blocker.
