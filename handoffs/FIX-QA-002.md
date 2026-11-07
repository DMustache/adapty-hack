# FIX-QA-002 handoff

- Updated `tests/test_analytics.py` fake cursor to model `INSERT ... RETURNING prediction_id` separately from the subsequent SELECT, while retaining the provenance and SQL assertions.
- Updated `scripts/gate.sh` to run the opt-in live M3 PostgreSQL/Grafana QA after Compose and smoke for M3 and later milestones, before writing the exact-SHA PASS marker. A failed live test stops the gate.
- Checks: `../develop/.venv/bin/python -m pytest -q` — 43 passed, 1 skipped (opt-in live test); targeted analytics/M3 static tests — 6 passed, 1 deselected; `bash -n scripts/gate.sh` and `git diff --check` passed.
- The full live M3 gate remains for Lead after integration. A likely separate issue is that the live QA test expects panel SQL alias `Mock churn risk`, while the Grafana worker changed it to `Mean mock churn probability`; this test file is outside this FIX job's ownership.
