# External ML Researcher Handoff — Churn Risk

The infrastructure team does **not** train or tune models. Please provide the following when ready:

1. **Artifact**: trusted Python package / ONNX / API endpoint, exact runtime/dependency versions, entrypoint and checksum. No arbitrary pickle uploaded over HTTP.
2. **Inference unit**: one currently active weekly/monthly subscriber per prediction. State whether separate category/platform models exist.
3. **Prediction horizon**: probability of **voluntary cancellation or non-renewal** for the *next renewal event* vs a fixed 7/30-day window; precisely define target. These are not interchangeable.
4. **Time cutoff**: features available at the instant a discount decision would be made. No future transaction data, renewal outcome or refund after cutoff.
5. **Inputs**: JSON Schema with exact feature names/types, null handling, event aggregation windows, examples and batch support.
6. **Outputs**: calibrated `churn_probability in [0,1]`, model version, calibration/evaluation report, date range and training provenance. If uncalibrated, label as risk score rather than probability.
7. **Tests**: deterministic input/output fixture, invalid input, one batch example, inference performance budget.
8. **Bias/limitations**: training data is synthetic Lumen only, potential leakage, distribution shift, churn label imbalance and category generalization limitations.
9. **Treatment**: no discount response labels exist; the ML model cannot estimate causal discount uplift from this dataset alone. Future treatment-effects modeling requires randomized arms and observed outcomes.

The infrastructure currently provides `MockChurnAdapter`, whose static risk values are not learned. To integrate a real model, implement `ModelAdapter.load/get_input_schema/predict` and register it; leave service routes/contracts unchanged unless Lead signs off.

---

## Status (2026-11-08): delivered model `lumen-temporal-catboost` 1.0.0

Full write-up with metrics: `docs/TEMPORAL_CHURN.md`.

| # | Requirement | Delivered |
|---|---|---|
| 1 | Artifact | CatBoost `.cbm` (no pickle) + `model.cbm.sha256` + `metadata.json` in `services/inference/models/temporal_catboost/`; the adapter refuses a checksum mismatch. Runtime: `catboost>=1.2,<2` |
| 2 | Inference unit | One active weekly/monthly paid subscriber at an instant `as_of_at`. One model for both plans and platforms |
| 3 | Prediction target | Non-renewal at the **next renewal event** (`renewal_due_at`), any reason. Not a fixed 7/30-day window |
| 4 | Time cutoff | Features use only events at or before `as_of_at`; a test rewrites later events and checks earlier features are unchanged. `cancellation_reason` is never used |
| 5 | Inputs | JSON Schema in `metadata.json` (served at `/v1/models/lumen-temporal-catboost/schema`); nulls allowed where documented. Batch: `adapter.predict_batch` |
| 6 | Outputs | `churn_probability` in [0, 1] plus model version. Holdout: Brier 0.0601, ECE 0.016, ROC-AUC 0.767, PR-AUC 0.518. Mean predicted 11.7% vs 10.1% actual (drift; recalibration tried and not deployed). Training window and provenance in `metadata.json` |
| 7 | Tests | Deterministic fixture, invalid input, batch, 2,000-snapshot performance budget, tampered artifact: `tests/test_temporal_adapter.py` |
| 8 | Bias / limitations | Synthetic data only. Most signal is auto-renew status: for subscribers with auto-renew still on, ROC-AUC is 0.640 at 1–6 days and no better than random at 15–30 days. No engagement data. Churn-rate level drifts |
| 9 | Treatment | No discount-response labels: the model predicts risk only, never uplift. Discount effects still need randomized tests (`/v1/retention/plan`) |

`MockChurnAdapter` remains available for demos. The real model is registered only when its artifact is present.
