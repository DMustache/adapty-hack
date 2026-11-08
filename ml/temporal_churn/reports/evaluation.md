# Temporal churn model: evaluation

Synthetic Lumen data. Observation cutoff 2026-11-03T00:07 UTC. Point-in-time snapshots of active weekly/monthly subscribers; target = no renewal at the next eligible renewal event.

- Train: 61,528 snapshots, 2,412 subscribers, as-of 2026-07-06 – 2026-10-04; every training renewal resolved before 2026-10-05.
- Untouched temporal holdout: 28,020 snapshots, 2,130 subscribers, as-of 2026-10-05 – 2026-10-31.
- Censored (renewal not yet resolved, excluded from train and test): 11,717 of 109,599 snapshots.

| Model | Brier (base rate) | Log loss | PR-AUC | ROC-AUC | ECE | Calib. slope / int. | Lost revenue in top 10% / 20% |
|---|---|---|---|---|---|---|---|
| static (baseline) | 0.0911 (0.0905) | 0.3290 | 0.118 | 0.552 | 0.0341 | 1.77 / +1.15 | 14.2% / 27.7% |
| temporal_behaviour | 0.0907 (0.0905) | 0.3273 | 0.118 | 0.556 | 0.0229 | 1.11 / -0.02 | 15.5% / 27.9% |
| temporal (**deployed**) | 0.0601 (0.0905) | 0.2337 | 0.518 | 0.767 | 0.0159 | 1.38 / +0.63 | 45.6% / 56.7% |

Brier improvement (subscriber-clustered bootstrap 95% CI; positive = second model better):

- temporal_behaviour vs static: +0.00032 (+0.00013 to +0.00052)
- temporal vs static: +0.03096 (+0.02785 to +0.03403)
- temporal vs temporal_behaviour: +0.03063 (+0.02738 to +0.03366)

## static

CatBoost {'depth': 3, 'iterations': 100, 'learning_rate': 0.03, 'l2_leaf_reg': 10} (chronological CV log loss per grid point: 0.3519, 0.3637, 0.3525, 0.3787, 0.3544, 0.3993)

| Days until renewal | n | Churn | Brier | PR-AUC |
|---|---|---|---|---|
| (-0.001, 1.0] | 3,906 | 9.6% | 0.0880 | 0.118 |
| (1.0, 2.0] | 3,782 | 9.9% | 0.0903 | 0.120 |
| (2.0, 3.0] | 4,380 | 9.7% | 0.0880 | 0.118 |
| (3.0, 5.0] | 6,949 | 10.7% | 0.0957 | 0.121 |
| (5.0, 8.0] | 7,035 | 10.8% | 0.0964 | 0.120 |
| (8.0, 31.0] | 1,968 | 7.4% | 0.0697 | 0.084 |

Mean predicted risk as renewal approaches:

| Days until renewal | Renewed | Churned |
|---|---|---|
| 8+ | 0.108 | 0.110 |
| 7 | 0.134 | 0.136 |
| 6 | 0.130 | 0.133 |
| 5 | 0.134 | 0.137 |
| 4 | 0.134 | 0.137 |
| 3 | 0.130 | 0.134 |
| 2 | 0.134 | 0.138 |
| 1 | 0.134 | 0.138 |

| Calibration bin | n | Mean predicted | Observed |
|---|---|---|---|
| 1 | 2,802 | 0.105 | 0.073 |
| 2 | 2,802 | 0.122 | 0.093 |
| 3 | 2,802 | 0.126 | 0.092 |
| 4 | 2,802 | 0.126 | 0.097 |
| 5 | 2,802 | 0.127 | 0.095 |
| 6 | 2,802 | 0.128 | 0.082 |
| 7 | 2,802 | 0.129 | 0.091 |
| 8 | 2,802 | 0.138 | 0.096 |
| 9 | 2,802 | 0.155 | 0.171 |
| 10 | 2,802 | 0.158 | 0.115 |

## temporal_behaviour

CatBoost {'depth': 3, 'iterations': 100, 'learning_rate': 0.03, 'l2_leaf_reg': 10} (chronological CV log loss per grid point: 0.3503, 0.3615, 0.3517, 0.3732, 0.3540, 0.3894)

| Days until renewal | n | Churn | Brier | PR-AUC |
|---|---|---|---|---|
| (-0.001, 1.0] | 3,906 | 9.6% | 0.0874 | 0.115 |
| (1.0, 2.0] | 3,782 | 9.9% | 0.0899 | 0.119 |
| (2.0, 3.0] | 4,380 | 9.7% | 0.0876 | 0.116 |
| (3.0, 5.0] | 6,949 | 10.7% | 0.0956 | 0.120 |
| (5.0, 8.0] | 7,035 | 10.8% | 0.0963 | 0.120 |
| (8.0, 31.0] | 1,968 | 7.4% | 0.0689 | 0.086 |

Mean predicted risk as renewal approaches:

| Days until renewal | Renewed | Churned |
|---|---|---|
| 8+ | 0.093 | 0.095 |
| 7 | 0.131 | 0.133 |
| 6 | 0.123 | 0.127 |
| 5 | 0.130 | 0.132 |
| 4 | 0.128 | 0.130 |
| 3 | 0.120 | 0.125 |
| 2 | 0.125 | 0.128 |
| 1 | 0.123 | 0.126 |

| Calibration bin | n | Mean predicted | Observed |
|---|---|---|---|
| 1 | 2,802 | 0.086 | 0.067 |
| 2 | 2,802 | 0.106 | 0.101 |
| 3 | 2,802 | 0.112 | 0.099 |
| 4 | 2,802 | 0.117 | 0.085 |
| 5 | 2,802 | 0.121 | 0.075 |
| 6 | 2,802 | 0.125 | 0.089 |
| 7 | 2,802 | 0.129 | 0.095 |
| 8 | 2,802 | 0.135 | 0.126 |
| 9 | 2,802 | 0.146 | 0.147 |
| 10 | 2,802 | 0.157 | 0.122 |

## temporal

CatBoost {'depth': 3, 'iterations': 100, 'learning_rate': 0.03, 'l2_leaf_reg': 10} (chronological CV log loss per grid point: 0.2538, 0.2577, 0.2545, 0.2633, 0.2565, 0.2753)

| Days until renewal | n | Churn | Brier | PR-AUC |
|---|---|---|---|---|
| (-0.001, 1.0] | 3,906 | 9.6% | 0.0250 | 0.803 |
| (1.0, 2.0] | 3,782 | 9.9% | 0.0392 | 0.686 |
| (2.0, 3.0] | 4,380 | 9.7% | 0.0462 | 0.616 |
| (3.0, 5.0] | 6,949 | 10.7% | 0.0734 | 0.399 |
| (5.0, 8.0] | 7,035 | 10.8% | 0.0904 | 0.203 |
| (8.0, 31.0] | 1,968 | 7.4% | 0.0458 | 0.467 |

Mean predicted risk as renewal approaches:

| Days until renewal | Renewed | Churned |
|---|---|---|
| 8+ | 0.052 | 0.381 |
| 7 | 0.124 | 0.125 |
| 6 | 0.106 | 0.216 |
| 5 | 0.107 | 0.257 |
| 4 | 0.093 | 0.393 |
| 3 | 0.071 | 0.532 |
| 2 | 0.061 | 0.611 |
| 1 | 0.053 | 0.748 |

| Calibration bin | n | Mean predicted | Observed |
|---|---|---|---|
| 1 | 2,802 | 0.045 | 0.027 |
| 2 | 2,802 | 0.052 | 0.031 |
| 3 | 2,802 | 0.058 | 0.041 |
| 4 | 2,802 | 0.066 | 0.049 |
| 5 | 2,802 | 0.079 | 0.062 |
| 6 | 2,802 | 0.091 | 0.067 |
| 7 | 2,802 | 0.103 | 0.091 |
| 8 | 2,802 | 0.112 | 0.099 |
| 9 | 2,802 | 0.121 | 0.103 |
| 10 | 2,802 | 0.439 | 0.436 |
