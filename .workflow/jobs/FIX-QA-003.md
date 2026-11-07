---
id: FIX-QA-003
milestone: M3
role: qa
status: READY
depends_on: []
owned_paths:
  - tests/test_m3_analytics_contract.py
---
# FIX-QA-003: Read the current mock-risk panel result by field meaning

## Failing live check
With M3 Analytics and Grafana changes integrated at `develop` SHA `fd05f24afd324ed6545c4b429e6b4fb76a8dddc8`, run `M3_QA_INTEGRATION=1 .venv/bin/python -m pytest -q tests/test_m3_analytics_contract.py -k postgres_ingestion` in `.worktrees/develop`. The live test fails with `KeyError: 'Mock churn risk'` after the panel SQL successfully returns a row. Expected: confirm that the mock-only panel excludes an external prediction and reports 0.8 for the mock fixture. Actual: the test looks up the old SQL alias, while the provisioned dashboard now calls it `Mean mock churn probability`. The earlier main-script gate had not invoked this opt-in check; Lead has synchronized that gate step before this job.

## Work
Update only the owned M3 QA test to inspect the current panel's numeric series without hard-coding an obsolete display alias. Keep the assertion that the mock value is 0.8 when a same-time external prediction with probability 0.1 exists. Preserve the live database assertions, read-only grants, and cleanup behavior. Do not change the dashboard solely to satisfy the test.

## Acceptance and handoff
The opt-in live test passes on the integrated M3 stack, fails if the mock-source SQL filter is removed, and the full M3 gate runs that test before its PASS marker. Run targeted checks, commit on `fix/FIX-QA-003`, write `handoffs/FIX-QA-003.md` with commands/results and blockers, and send Lead the SHA. Lead integrates and reruns the exact-SHA M3 gate.
