---
id: FIX-GR-003
milestone: M5
role: grafana
priority: P1
status: READY
depends_on: []
owned_paths: [grafana/]
---
# FIX-GR-003: Replace stale model status

At M5 `develop` SHA `94b0962`, the Data and Model Health panel always says no external model is loaded, despite stored external predictions. Replace it with read-only prediction source, model, version and count rows from `churn_predictions`; show an explicit no-external-predictions row when absent. Label these as stored synthetic evidence, not service health or real-customer approval. Also remove the stale model-not-delivered description from the source inventory panel. Verify the query on the live M5 database and an empty predictions table. Regression test: FIX-QA-010.
