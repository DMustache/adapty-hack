# Discount Advisor I/O candidate (reviewed 2026-11-07)

Source reviewed: `origin/model-implementation` at `253b5bd65cd71c69c5b2308ae4e0b097a2e31095`.
This is a **cohort discount experiment advisor**, not a churn prediction model. It has no
preloaded churn weights, per-user churn probability, or training loop. Do not register it
as `ModelAdapter` or put its output in `churn_predictions`. Its synthetic Lumen inputs
and assumed treatment response also cannot validate a live discount outcome.

## Boundary

Run the advisor as a versioned offline batch calculation. Keep the two existing
services: the inference service owns the calculation/experiment proposal; the
analytics service stores its immutable report; Grafana reads that store with the
read-only database role. The first implementation may import audited source files
from the unrelated-history branch; do not merge the branch wholesale or import its
tracked `__pycache__` files. Pin the source commit and dependency versions.

Input is one `discount-advisor-run` JSON document plus a configured, trusted
`DISCOUNT_DATA_DIR` containing `users.csv.gz` and `transactions.csv.gz`. A request
does not contain a filesystem path or `ADAPTY_SECRET`. The caller supplies:

```json
{
  "schema_version": "0.1",
  "app_id": "Lumen synthetic",
  "run_id": "onboarding-2026-11-07-v1",
  "audience": {"placement": "onboarding", "segment_dimension": null, "segment_value": null},
  "offer": {"discount_duration": "first_payment", "horizon_months": 12, "max_discount": 0.4},
  "assumptions": {"lift_at_20pct": {"low": 0.05, "mode": 0.2, "high": 0.5},
                  "market_ceiling_multiplier": 2.0, "incremental_buyer_value_ratio": 0.85,
                  "step_up_churn_factor": 0.3, "store_fee": 0.15,
                  "include_sampling_uncertainty": true, "simulation_seed": 7},
  "experiment": {"discount_arms": 1, "allocation": 1.0,
                 "max_weeks": 8, "min_scenario_share": 0.5,
                 "weekly_eligible_override": null}
}
```

Allowed segment dimensions are `country`, `price_tier`, `platform`,
`acquisition_channel`, and `flow`. Allowed durations are `first_payment`, `1m`,
`3m`, `all`; horizons are 3, 6, 12 months. Reject invalid or infeasible
assumptions explicitly. The run must be deterministic for the same input, source
version, and dataset digest. An existing `run_id` with different inputs is a
conflict, not an overwrite.

Output is one `discount-advisor-report` JSON document, with numeric values rather
than formatted Streamlit text:

```json
{
  "schema_version": "0.1",
  "run_id": "onboarding-2026-11-07-v1",
  "app_id": "Lumen synthetic",
  "advisor_source_sha": "253b5bd65cd71c69c5b2308ae4e0b097a2e31095",
  "dataset_sha256": "<digest of both source files and their order>",
  "data_kind": "synthetic",
  "observed_through_utc": "2026-11-03T00:07:04Z",
  "created_at_utc": "<UTC timestamp>",
  "audience": {"placement": "onboarding", "segment_dimension": null, "segment_value": null},
  "offer": {"discount_duration": "first_payment", "horizon_months": 12},
  "baseline": {"mature_installs": 0, "payers": 0,
               "first_paid_14d_conversion": 0.0, "first_paid_14d_wilson_95": [0.0, 0.0],
               "value_per_payer_usd": 0.0, "value_extrapolated_share": 0.0,
               "discount_touched_revenue_share": 0.0, "weekly_eligible": 0.0,
               "weekly_eligible_source": "synthetic_dataset"},
  "assumptions": {"<validated run assumptions>": "<values>"},
  "candidates": [{"discount_fraction": 0.2, "break_even_relative_conversion_lift": 0.0,
                  "break_even_conversion": 0.0, "assumed_lift_mode": 0.0,
                  "scenario_share_above_baseline": 0.0,
                  "assumed_revenue_delta_per_install_usd": 0.0,
                  "users_per_arm": 0, "duration_weeks_including_wait": 0.0,
                  "verdict": "worth_testing"}],
  "recommendation": {"action": "keep_full_price", "discount_fraction": null,
                     "reason": "<specific reason>", "primary_metric": "first_paid_receipt_within_14d",
                     "review_after_days": 0},
  "provenance": {"baseline": "observed_synthetic", "break_even": "calculated",
                 "response": "assumed_scenario", "treatment_effect_observed": false}
}
```

The zero values above illustrate the shape, not a computed result. The worker
must replace them with actual calculations and suppress a recommendation for
small or unsupported audiences. Store the full validated run input alongside
the report, so assumptions and traffic overrides remain inspectable. Preserve
the source observation cutoff; `expires_at` after that cutoff is not an outcome.

## Grafana

Add a separate provisioned **Discount Advisor — synthetic scenarios** dashboard.
Show (1) baseline 14-day paid conversion with Wilson interval and mature-install
count, (2) first-paid conversion break-even by discount, (3) scenario share above
baseline and assumed revenue delta by discount, (4) sample size and duration,
and (5) recommendation plus input assumptions, dataset/source version and
observation cutoff. Every candidate panel must label `assumed_scenario` versus
`calculated`; it must not say realized uplift, saved revenue, or churn risk.
Filter by `run_id` and audience to avoid mixing runs with different assumptions.

## Adapty A/B handoff

Adapty's regular A/B test splits a **single placement** between published flows
or paywalls. It cannot consume the existing `RetentionPlanResult` per-user arm
CSV directly. The CLI account currently has flow placements and no verified discount
treatment flow; Onboarding and Main already have live tests. A 20–40% discount
recommendation from synthetic assumptions must not silently replace either.

Generate a **draft manifest** only when `recommendation.action=test_discount`.
It must name the app and placement UUID, full-price control flow UUID, published
discount treatment flow UUID, audience/segment ID or All users, arm weights
summing to 100, product/price/eligibility mapping, primary metric and guardrails,
run ID, advisor source/dataset digests, and assumption labels. Validate that
the flow actually presents the intended discount and that the cohort/placement
match the report. A missing treatment flow, incompatible audience, or existing
live test is a clear `not_ready` result; never guess IDs or create live offers.
The operator can turn a reviewed manifest into a **draft** Adapty flow A/B test.
Starting/replacing a live test remains a separate explicit action with a
placement impact review. `ADAPTY_SECRET` stays local and must never enter JSON,
Git, Grafana, logs, or the browser.

This advisor's install-to-first-paid metric and the existing retention planner's
active-subscriber-to-next-renewal metric are different populations and outcomes.
Keep their reports and Grafana panels separate. The external ML owner still
needs to deliver the churn model contract described in `MODEL_HANDOFF.md`.
