---
id: FIX-QA-002
milestone: M3
role: qa
status: READY
depends_on: []
owned_paths:
  - tests/test_analytics.py
  - scripts/gate.sh
---
# FIX-QA-002: Update fake cursor and include live M3 QA in gate

## Failing gate
`PATH=.worktrees/develop/.venv/bin:$PATH bash scripts/gate.sh M3` failed at `develop` SHA `5d83c5ade7d07b447a31513de03971143eb5fe5c`. Log: `.worktrees/develop/.agent-runtime/gates/M3.log`. Expected: the existing provenance test passes against immutable prediction ingestion. Actual: `tests/test_analytics.py::test_prediction_model_provenance_survives_ingest_and_read` raises `TypeError` because its fake cursor treats the new `INSERT ... RETURNING prediction_id` fetch as a SELECT result and has no selected columns.

## Work
Update only the fake database in `tests/test_analytics.py` to model the insert-returning result and subsequent readback while still checking SQL-selected provenance fields. Do not weaken the test's assertions. Extend `scripts/gate.sh` so M3 (and later milestones using the same analytics stack) runs the opt-in `tests/test_m3_analytics_contract.py` PostgreSQL/Grafana integration check after Compose starts and before the smoke PASS marker. Keep all checks on the captured `develop` SHA and preserve failure propagation/logging. Do not edit service, Grafana, contracts, or other QA files.

## Acceptance and handoff
The existing provenance test passes, full pytest passes, and the exact-SHA M3 gate runs the live integration check rather than skipping it. A failing live check prevents the marker. Run targeted checks, commit on `fix/FIX-QA-002`, write `handoffs/FIX-QA-002.md` with results and blockers, and send Lead the commit SHA. Lead integrates and reruns the M3 gate.
