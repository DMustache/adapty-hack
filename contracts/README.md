# Frozen contract source of truth

Schemas are generated from `shared/contracts/models.py` by Lead using `python scripts/export_schemas.py` and committed *before* job worktrees spawn. Backend and QA must use the same schemas.

- `churn-prediction-request.schema.json`: a single active subscriber, horizon, flexible features.
- `churn-prediction-result.schema.json`: externally obtained churn probability or explicit mock fixture.
- `retention-plan-request.schema.json`: weekly/monthly candidate list, prices, budget, discounts, deterministic seed, holdout share.
- `retention-plan-result.schema.json`: randomized experiment arms, break-even thresholds, worst-case exposure. No treatment-uplift model.
- `actual-observation.schema.json`: observed outcomes only, separate ingestion stream.

API endpoint contracts: Inference `POST /v1/predict`, `POST /v1/retention/plan`; Analytics `POST /v1/ingest/predictions`, `POST /v1/ingest/experiments`, `GET /v1/experiments/{id}`. API docs `/docs`.

## M5 temporal and A/B lifecycle contracts

The new `temporal-churn-request.schema.json` narrows the existing v1 prediction
request only for `lumen-temporal-catboost`. The unmodified generated v1 schema
and other model requests remain valid. Its 23 feature definitions are copied
from the immutable artifact metadata; the service must also check the UTC
date ordering, horizon ceiling, and agreement between the unrounded
`days_until_renewal` feature and the dates. JSON Schema alone does not check
cross-field arithmetic.

The model-specific request and seven lifecycle record schemas have matching
examples here. Lifecycle `schema_version: 1.0` is independent of the unchanged
v1 route version. An event is immutable under its idempotency key; duplicates
with different content conflict. `source: simulated` means a deterministic
demo record, never an observed Adapty event. Operational Adapty assignment
and exposure ingestion needs a verified event-level source and identity map;
the synthetic CSV's `ab_test` field is insufficient.

The cohort record is a one-user membership example; a cohort is the set of
members with one `cohort_id`, `policy_version`, and `membership_cutoff_at`.
The profile reference and restricted identity-map reference are audit handles,
not raw customer identifiers. Draft-test IDs and content IDs must be replaced
with verified tenant values before a real draft is created. Proposal arms
from `retention-plan-result` never become `actual-assignment` records.
