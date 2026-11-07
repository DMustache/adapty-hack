# FIX-AN-001 handoff

- Changed `services/analytics/app/main.py`: the churn-risk endpoint now uses an unfiltered query without parameters or a filtered query with one bound `app_id` parameter. Response fields and ordering are unchanged.
- Checks: `pytest -q tests/test_analytics.py` passed (1 test); direct TestClient check of both query branches passed; `git diff --check` passed.
- Integration verification still needed: rerun the M0 Docker/HTTP gate on `develop` after all fixes are merged.
- Blockers: none.
