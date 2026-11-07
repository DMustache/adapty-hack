# FIX-QA-001 handoff

- Changed `tests/test_analytics.py` to exercise both filtered and unfiltered churn-risk reads through the HTTP endpoint with a fake database cursor.
- The test checks returned point order, SQL ordering, and bind parameters. It rejects the nullable `IS NULL` bind that produced the PostgreSQL error.
- `../develop/.venv/bin/python -m pytest -q tests/test_analytics.py`: 2 expected failures against the old query, 1 pass (health check).
- No blockers. Run the targeted test after integrating `FIX-AN-001`, then the M0 gate on `develop`.
