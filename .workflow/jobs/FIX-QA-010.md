---
id: FIX-QA-010
milestone: M5
role: qa
priority: P1
status: READY
depends_on: []
owned_paths: [tests/]
---
# FIX-QA-010: Cover dynamic model inventory

At M5 `develop` SHA `94b0962`, `tests/test_m5_offline_dashboards.py` requires the obsolete hard-coded no-model message. Replace that assertion with a check that the model panel queries stored predictions and does not claim deployment status. Exercise its SQL against a database with external and mock predictions, and against an empty prediction table; require distinct source/model/version/count rows and an explicit no-external-predictions state. Keep the offline dashboards read-only.
