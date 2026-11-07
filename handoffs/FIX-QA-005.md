# FIX-QA-005 handoff

- Changed only `tests/test_m3_analytics_contract.py`: the seeded 10% offer arm now uses the planner's `discount_10pct` name, so the break-even panel's offer-arm filter is exercised by the live assertion.
- Static checks: `../develop/.venv/bin/python -m pytest -q tests/test_m3_analytics_contract.py` passed (2 passed, 1 opt-in skipped); Ruff and `git diff --check` passed.
- Live check: with develop `.env` loaded and `COMPOSE_PROJECT_NAME=develop`, `M3_QA_INTEGRATION=1 ../develop/.venv/bin/python -m pytest -q tests/test_m3_analytics_contract.py -k postgres_ingestion` passed (1 passed, 2 deselected) against the integrated develop Docker stack. The test verified panels 2–4 returned rows, mock-source separation, read-only grants, and cleaned its fixture rows.
- Blockers: none. Lead should integrate this branch and rerun the exact-SHA M3 gate.
