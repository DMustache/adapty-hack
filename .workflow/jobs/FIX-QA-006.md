---
id: FIX-QA-006
milestone: M5
role: qa
status: READY
depends_on: [M5-GR-005]
owned_paths: [tests/]
---
# Update historical M3 dashboard assertions for the four-dashboard contract

Failing command: `.venv/bin/python -m pytest -q` on develop `f000671`. `test_m3_dashboard_provisioning_and_scenario_semantics` expects the old mock scenario panels at `smart-retention`; M5-GR-005 intentionally repurposes that UID as source-honest campaign tracking. Retain the M3 live API persistence/idempotency checks but remove panel assertions tied to the retired dashboard. Assert the current four-dashboard provisioned shape instead. Expected: all unit tests pass; no mock data is presented as observed campaign outcomes. Add a regression handoff.
