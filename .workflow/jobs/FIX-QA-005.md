---
id: FIX-QA-005
milestone: M3
role: qa
status: READY
depends_on: []
owned_paths:
  - tests/test_m3_analytics_contract.py
---
# FIX-QA-005: Use planner arm name in live dashboard fixture

## Failing live check
With the integrated M3 stack on `develop` SHA `f6c2a2d17d93a78c5b029150e168deab5f18ba83`, `M3_QA_INTEGRATION=1 .venv/bin/python -m pytest -q tests/test_m3_analytics_contract.py -k postgres_ingestion` fails when the break-even panel query returns zero rows. Expected: the seeded scenario offer appears in panels 2–4. Actual: the QA fixture uses arm `offer_10`, while the real planner emits `discount_10pct` and the dashboard correctly filters offer arms with `LIKE 'discount_%'`.

## Work
Change only the owned M3 QA fixture to use the planner's actual 10% discount arm name. Preserve the dashboard SQL assertions, mock/external separation check, budget and break-even data checks, read-only privilege checks, and cleanup. Do not loosen the panel query or change the public schema.

## Acceptance and handoff
The opt-in live test passes against integrated M3 services and still fails if offer-arm dashboard rows are absent. Run targeted checks, commit on `fix/FIX-QA-005`, write `handoffs/FIX-QA-005.md`, and send Lead SHA. Lead integrates and reruns the exact-SHA M3 gate.
