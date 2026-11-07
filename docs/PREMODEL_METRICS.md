# Pre-model dashboard and test contract

This is the M5 infrastructure wave that can run before an external churn model arrives. It uses persisted `churn_predictions` and immutable `retention_experiments` only. Seeded `prediction_source = external` rows are **test fixtures**, not evidence that an external model is loaded.

## Prediction view

Reapply M5-GR-001's separate Churn Predictions dashboard, then add a compact summary for the selected UTC time range, app, model version and renewal horizon: external prediction count, mean, median and 90th percentile of stored probabilities, and hours since the latest prediction. All are descriptive summaries of stored outputs. Do not call them accuracy, calibration, churn rate or user coverage: the database has no eligible-population denominator or observed churn labels. Keep mock rows in their own visibly labeled panel. With no external rows, show an explicit empty status and no external numeric summary. Flag future-dated predictions as timestamp anomalies rather than treating a negative age as freshness. Do not show user IDs.

## Scenario view

Show the stored budget, maximum face-value exposure, unallocated budget, baseline revenue at risk, arm counts and break-even hurdle with a selectable experiment ID. Add cap utilization as `max_allocated_discount_exposure_usd / budget_usd` only when the budget is positive; a zero budget has no utilization percentage. Use proposal time in UTC. Label every number as a scenario, never realized spend, saved revenue, measured uplift or an optimal discount. Keep `actual_observations` out of the scenario calculations.

There is no prediction-to-experiment foreign key in the current v1 contracts. The dashboards must not claim that a particular prediction caused an assignment or an outcome. M5-LD-001 and later event-lineage jobs own that join.

## Test triangle

1. **Unit and contract:** independent expected values for probability summaries, cent-level exposure/cap utilization, infeasible break-even cases, randomized control, v1 schemas, and invalid probability or malformed request rejection.
2. **PostgreSQL and Grafana integration:** fixture external and mock rows at probability boundaries, version/horizon filters, zero external rows, future timestamp, read-only SQL privileges, query results, immutable retries and no cross-source contamination. Check scenario figures against persisted plans, including zero budget.
3. **Fresh Compose end-to-end:** HTTP prediction to analytics readback, planning to immutable experiment readback, provisioned dashboards and panel data from the same run. An external-looking fixture must never be described as a loaded model. Run this checkpoint on an exact `develop` SHA and record the log; it is not the final M5 milestone gate.

Passing this wave demonstrates infrastructure calculations and presentation only. M5 is complete only after the separately delivered model, frozen lifecycle contracts, authorized Adapty draft path and event-lineage gate satisfy `M5.md`.
