# Churn model with app-usage features vs the deployed baseline (SIMULATED – pipeline check, not a result)

> **SIMULATED – pipeline check, not a result.** Usage events are synthetic; no accuracy claim can be made from this.

Observation cutoff 2026-11-03T00:07 UTC; holdout from 2026-10-05. Train 61,528 / test 28,020 snapshots.

Usage coverage: train 79.3% of snapshots (1,909 subscribers), test 79.1% (1,687).

| Model | Features | Brier (base rate) | PR-AUC | ROC-AUC | ECE | Fold Briers |
|---|---|---|---|---|---|---|
| temporal (baseline, deployed) | 23 | 0.0601 (0.0905) | 0.518 | 0.767 | 0.0159 | 0.0665, 0.0663, 0.0679 |
| temporal_usage | 31 | 0.0601 (0.0905) | 0.518 | 0.767 | 0.0161 | 0.0665, 0.0665, 0.0679 |

Brier gain, usage vs baseline (positive = usage better): -0.00000 (95% CI -0.00004 to +0.00004).
Better in every fold: False; CI above zero: False; **passes: False**.

- Test snapshots with usage (n=22,174): Brier baseline 0.0600, usage 0.0600
- Test snapshots without usage (n=5,846): Brier baseline 0.0605, usage 0.0605

**Verdict:** SIMULATED – pipeline check, not a result. The usage features were computed from synthetic activity, so this shows only that the pipeline runs end to end; it says nothing about real accuracy. Keep the deployed model.

## temporal: by days until renewal

| Days | n | Churn | Brier | PR-AUC |
|---|---|---|---|---|
| (-0.001, 1.0] | 3,906 | 9.6% | 0.0250 | 0.803 |
| (1.0, 2.0] | 3,782 | 9.9% | 0.0392 | 0.686 |
| (2.0, 3.0] | 4,380 | 9.7% | 0.0462 | 0.616 |
| (3.0, 5.0] | 6,949 | 10.7% | 0.0734 | 0.399 |
| (5.0, 8.0] | 7,035 | 10.8% | 0.0904 | 0.203 |
| (8.0, 31.0] | 1,968 | 7.4% | 0.0458 | 0.467 |

## temporal_usage: by days until renewal

| Days | n | Churn | Brier | PR-AUC |
|---|---|---|---|---|
| (-0.001, 1.0] | 3,906 | 9.6% | 0.0249 | 0.802 |
| (1.0, 2.0] | 3,782 | 9.9% | 0.0392 | 0.687 |
| (2.0, 3.0] | 4,380 | 9.7% | 0.0463 | 0.614 |
| (3.0, 5.0] | 6,949 | 10.7% | 0.0734 | 0.397 |
| (5.0, 8.0] | 7,035 | 10.8% | 0.0903 | 0.206 |
| (8.0, 31.0] | 1,968 | 7.4% | 0.0458 | 0.467 |
