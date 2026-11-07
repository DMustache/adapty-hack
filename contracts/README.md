# Frozen contract source of truth

Schemas are generated from `shared/contracts/models.py` by Lead using `python scripts/export_schemas.py` and committed *before* job worktrees spawn. Backend and QA must use the same schemas.

- `churn-prediction-request.schema.json`: a single active subscriber, horizon, flexible features.
- `churn-prediction-result.schema.json`: externally obtained churn probability or explicit mock fixture.
- `retention-plan-request.schema.json`: weekly/monthly candidate list, prices, budget, discounts, deterministic seed, holdout share.
- `retention-plan-result.schema.json`: randomized experiment arms, break-even thresholds, worst-case exposure. No treatment-uplift model.
- `actual-observation.schema.json`: observed outcomes only, separate ingestion stream.

API endpoint contracts: Inference `POST /v1/predict`, `POST /v1/retention/plan`; Analytics `POST /v1/ingest/predictions`, `POST /v1/ingest/experiments`, `GET /v1/experiments/{id}`. API docs `/docs`.
