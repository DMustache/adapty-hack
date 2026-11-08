# External ML Researcher Handoff — Churn Risk (historical request)

This is the original delivery checklist. The unchanged `lumen-temporal-catboost` 1.0.0 artifact is now integrated for the synthetic hackathon demo; [M5's model review](../handoffs/M5-ML-001.md) records its exact target, checksum and use limits.

The infrastructure team does **not** train or tune models. Please provide the following when ready:

1. **Artifact**: trusted Python package / ONNX / API endpoint, exact runtime/dependency versions, entrypoint and checksum. No arbitrary pickle uploaded over HTTP.
2. **Inference unit**: one currently active weekly/monthly subscriber per prediction. State whether separate category/platform models exist.
3. **Prediction horizon**: define the exact next-renewal target versus a fixed 7/30-day window. The delivered model targets failure to renew for any reason at the next eligible renewal, including billing failure and refund; this is broader than voluntary cancellation.
4. **Time cutoff**: features available at the instant a discount decision would be made. No future transaction data, renewal outcome or refund after cutoff.
5. **Inputs**: JSON Schema with exact feature names/types, null handling, event aggregation windows, examples and batch support.
6. **Outputs**: calibrated `churn_probability in [0,1]`, model version, calibration/evaluation report, date range and training provenance. If uncalibrated, label as risk score rather than probability.
7. **Tests**: deterministic input/output fixture, invalid input, one batch example, inference performance budget.
8. **Bias/limitations**: training data is synthetic Lumen only, potential leakage, distribution shift, churn label imbalance and category generalization limitations.
9. **Treatment**: no discount response labels exist; the ML model cannot estimate causal discount uplift from this dataset alone. Future treatment-effects modeling requires randomized arms and observed outcomes.

The infrastructure provides `MockChurnAdapter`, whose static risk values are not learned, and loads the fixed `lumen-temporal-catboost` 1.0.0 artifact supplied at `origin/temporal-churn` commit `7dc9a96`. Its later history-feature ablation did not replace the artifact. M5-ML-001 approved this exact version for the local synthetic demo, with no operational calibration approval for real customers. Both adapters use the `ModelAdapter.load/get_input_schema/predict` boundary; do not train, tune, recalibrate, extend or replace the model.
