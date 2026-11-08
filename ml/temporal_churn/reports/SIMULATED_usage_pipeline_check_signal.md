# Churn model with app-usage features vs the deployed baseline (SIMULATED – pipeline check, not a result)

> **SIMULATED – pipeline check, not a result.** Usage events are synthetic; no accuracy claim can be made from this.

Observation cutoff 2026-11-03T00:07 UTC; holdout from 2026-10-05. Train 61,528 / test 28,020 snapshots.

Usage coverage: train 78.9% of snapshots (1,927 subscribers), test 79.0% (1,683).

| Model | Features | Brier (base rate) | PR-AUC | ROC-AUC | ECE | Fold Briers |
|---|---|---|---|---|---|---|
| temporal (baseline, deployed) | 23 | 0.0601 (0.0905) | 0.518 | 0.767 | 0.0159 | 0.0665, 0.0663, 0.0679 |
| temporal_usage | 31 | 0.0588 (0.0905) | 0.555 | 0.810 | 0.0147 | 0.0656, 0.0647, 0.0667 |

Brier gain, usage vs baseline (positive = usage better): +0.00130 (95% CI +0.00088 to +0.00169).
Better in every fold: True; CI above zero: True; **passes: True**.

- Test snapshots with usage (n=22,136): Brier baseline 0.0586, usage 0.0569
- Test snapshots without usage (n=5,884): Brier baseline 0.0658, usage 0.0658

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
| (-0.001, 1.0] | 3,906 | 9.6% | 0.0242 | 0.851 |
| (1.0, 2.0] | 3,782 | 9.9% | 0.0381 | 0.739 |
| (2.0, 3.0] | 4,380 | 9.7% | 0.0448 | 0.674 |
| (3.0, 5.0] | 6,949 | 10.7% | 0.0716 | 0.458 |
| (5.0, 8.0] | 7,035 | 10.8% | 0.0890 | 0.251 |
| (8.0, 31.0] | 1,968 | 7.4% | 0.0456 | 0.479 |
