# FIX-BE-002 handoff

- Changed `services/inference/app/economics.py` to report unallocated budget as the stated budget minus allocated whole-cent exposure. The spendable budget still rounds down to cents and each exposure rounds up, so allocation remains conservative.
- Updated the colocated M2 regression for fractional-cent budgets: $0.005 remains entirely unallocated; a $0.019 budget with a $0.01 offer leaves $0.009 unallocated.
- Verification: `../develop/.venv/bin/python -m pytest -q services/inference/test_economics_m2.py tests/test_m2_economics_contract.py tests/test_economics.py` — 27 passed. `../develop/.venv/bin/python -m ruff check services/inference/app/economics.py services/inference/test_economics_m2.py` and `git diff --check` passed.
- Blockers: none. Lead must integrate and rerun the full M2 gate on `develop`.
