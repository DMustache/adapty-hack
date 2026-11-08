# Recalibration: predicted vs actual churn rate

Calibration window: as-of 2026-09-14 – 2026-10-05, 17,146 snapshots with renewals resolved before the holdout (actual churn 12.1%; the out-of-time model predicted 12.8%). Platt: logit(p') = +2.272 + 2.032 · logit(p). Evaluated on the untouched holdout.

**Verdict:** Platt does NOT improve Brier, ECE and the overall rate on the holdout → not deployed.

| Variant | Mean predicted | Actual | Brier | Log loss | ECE | Calib. slope / int. | ROC-AUC | PR-AUC |
|---|---|---|---|---|---|---|---|---|
| before (deployed v1.0.0) | 11.7% | 10.1% | 0.0601 | 0.2337 | 0.0159 | 1.38 / +0.63 | 0.767 | 0.518 |
| after: Platt | 11.2% | 10.1% | 0.0604 | 0.2335 | 0.0167 | 0.68 / -0.91 | 0.767 | 0.518 |
| sensitivity: intercept shift | 11.2% | 10.1% | 0.0600 | 0.2329 | 0.0120 | 1.38 / +0.72 | 0.767 | 0.518 |
| sensitivity: isotonic | 11.0% | 10.1% | 0.0608 | 0.2417 | 0.0189 | 0.46 / -1.41 | 0.766 | 0.489 |

Mean absolute error of group churn rates (predicted vs actual), by grouping:

| Grouping | before (deployed v1.0.0) | after: Platt | sensitivity: intercept shift | sensitivity: isotonic |
|---|---|---|---|---|
| plan | 1.30% | 1.48% | 0.95% | 1.82% |
| days_bucket | 1.50% | 1.41% | 1.14% | 1.62% |
| acquisition_channel | 1.45% | 1.05% | 1.07% | 0.93% |
| country | 1.94% | 1.57% | 1.63% | 1.48% |
| flow | 1.51% | 1.98% | 1.26% | 2.18% |

By plan:

| plan | n | Actual | Before | After (Platt) |
|---|---|---|---|---|
| monthly | 3,331 | 7.4% | 8.3% | 5.9% |
| weekly | 24,689 | 10.4% | 12.1% | 11.9% |

By days_bucket:

| days_bucket | n | Actual | Before | After (Platt) |
|---|---|---|---|---|
| (-0.001, 1.0] | 3,906 | 9.6% | 12.0% | 9.6% |
| (1.0, 2.0] | 3,782 | 9.9% | 11.6% | 9.3% |
| (2.0, 3.0] | 4,380 | 9.7% | 11.5% | 9.8% |
| (3.0, 5.0] | 6,949 | 10.7% | 12.4% | 12.5% |
| (5.0, 8.0] | 7,035 | 10.8% | 12.0% | 14.3% |
| (8.0, 31.0] | 1,968 | 7.4% | 7.6% | 5.2% |

Calibration table (deciles of predicted risk):

| Decile | Before: predicted / observed | After: predicted / observed |
|---|---|---|
| 1 | 0.045 / 0.027 | 0.019 / 0.027 |
| 2 | 0.052 / 0.031 | 0.026 / 0.031 |
| 3 | 0.058 / 0.041 | 0.032 / 0.041 |
| 4 | 0.066 / 0.049 | 0.043 / 0.049 |
| 5 | 0.079 / 0.062 | 0.063 / 0.062 |
| 6 | 0.091 / 0.067 | 0.084 / 0.067 |
| 7 | 0.103 / 0.091 | 0.106 / 0.091 |
| 8 | 0.112 / 0.099 | 0.125 / 0.099 |
| 9 | 0.121 / 0.103 | 0.148 / 0.103 |
| 10 | 0.439 / 0.436 | 0.472 / 0.436 |
