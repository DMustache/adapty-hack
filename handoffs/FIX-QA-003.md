# FIX-QA-003 handoff

- Updated `tests/test_m3_analytics_contract.py` to read the mock-risk panel's single numeric series without assuming a display alias. The live fixture still inserts a mock risk of 0.8 and a same-time external risk of 0.1, so removing the SQL `prediction_source='mock'` filter makes the 0.8 assertion fail.
- Checks: `../develop/.venv/bin/python -m pytest -q tests/test_m3_analytics_contract.py` passed (2 passed, 1 opt-in skipped); `../develop/.venv/bin/python -m ruff check tests/test_m3_analytics_contract.py` passed; `git diff --check` passed.
- An attempted live run against the existing develop Compose stack failed before ingestion at Grafana authentication (HTTP 401). Grafana logs report the admin account temporarily blocked after too many incorrect login attempts. Lead will recreate the container and run the exact-SHA M3 gate after integration.
- Blockers: no code blocker. Full live gate remains for Lead.
