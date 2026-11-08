# Retention offers: churn predictions → renewal-discount experiments

Connects the deployed churn model to the existing retention planner and shows it in the Streamlit app
(**Retention offers** tab). The acquisition Discount Advisor tabs are unchanged.

> **No observed discount-response data.** Everything here is a break-even threshold (how much renewal would have to
> improve to pay for a discount) or a randomized test design. Nothing predicts uplift, picks an optimal discount or
> promises revenue.

## Data flow

```text
CatBoost (POST /v1/predict, plan_type now optional) ─► analytics ─► PostgreSQL churn_predictions
                                                                        │
                                       GET /v1/retention/at-risk  ◄─────┘   latest valid prediction per subscriber
                                                │
discount_advisor/retention_offers.py ◄──────────┘   revenue at risk, exposure, break-even scenarios, sample size
        │  preview: services.inference.app.economics.make_plan (same code as the API)
        └► POST /v1/retention/plan ─► analytics ─► PostgreSQL retention_experiments (immutable per experiment_id)
```

## "Latest valid prediction" (`GET /v1/retention/at-risk`)

- **Valid:** `model_id` = `lumen-temporal-catboost` (optionally one `model_version`/`app_id`), with `as_of_at`,
  `renewal_due_at` and `renewal_price_usd`.
- **Reference time:** `as_of` if given, else the newest valid `as_of_at` (the data's own clock; ≈ now when scoring is
  live).
- Per subscriber, the newest valid prediction at or before the reference time. It's **dropped, not replaced by an
  older one**, if its renewal is already due or it's older than `max_age_days` (default 7). The response counts each
  exclusion.
- Sorted by churn probability × renewal price. All times in UTC.

## Calculations (all reused)

| Output | Formula | Source |
|---|---|---|
| Revenue at risk | p × renewal price, rounded to cents half-up | planner's `cents()` |
| Break-even renewal | p₀ ÷ (1 − d), i.e. +d/(1−d) relative for everyone (20% → +25%) | planner's `break_even()` |
| Can break even | p₀ ÷ (1 − d) ≤ 1, i.e. churn probability ≥ d | planner's `break_even()` |
| Discount cost on baseline renewers | Σ (1 − p) × price × d = the revenue extra renewals must win back | arithmetic |
| Users per arm | two-proportion test at exactly the break-even change, α 0.05 Bonferroni-split, power 0.8 | Discount Advisor `ab_sample_size()` |
| Experiment | randomized control + rotating discount arms, budget-capped face-value exposure | planner's `make_plan()` / `/v1/retention/plan` |

## Setup

- New column `churn_predictions.plan_type` (`postgres/init/005-retention-offers.sql`; run it once on an existing
  volume). Older rows without it are shown but left out of experiments.
- `scripts/score_temporal_snapshots.py` now sends `plan_type`.
- The app reads `ANALYTICS_URL` (default `http://127.0.0.1:8002`) and `INFERENCE_URL` (default
  `http://127.0.0.1:8001`); both can be changed in the tab.

## Tests

- `tests/test_retention_offers.py` (11): real PostgreSQL with all init SQL, from `$TEST_DATABASE_URL` or a
  throwaway `pixeltable-pgserver`; skipped if neither is available. Covers:
  - the real CatBoost artifact → stored → retrieved → planned → stored experiment, with the preview fingerprint equal
    to the API's;
  - latest-valid rules (newest wins, invalid newer row falls back, already-due excluded without fallback, stale,
    other model, app/version filters, `as_of` time travel);
  - parameter validation; the plan_type constraint;
  - scenarios equal to the planner's arithmetic, including the break-even revenue identity;
  - no-claims wording; unreachable service.
- `discount_advisor/tests/test_retention_tab.py` (4): AppTest of the tab (metrics, filters, empty selection,
  register success and failure) and the full app with services down (the tab shows an error; the acquisition
  recommendation still renders).
