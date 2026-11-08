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

The infrastructure currently provides `MockChurnAdapter`, whose static risk values are not learned. `origin/temporal-churn` at `7dc9a96` supplies a candidate `lumen-temporal-catboost` 1.0.0 artifact, adapter and fixture. Its later history-feature ablation did not replace the artifact. M5-ML-001 requires external owner acceptance, especially of its any-reason next-renewal target and calibration, before it can become active. Integrate through `ModelAdapter.load/get_input_schema/predict`; leave service routes/contracts unchanged unless Lead freezes an additive revision.
