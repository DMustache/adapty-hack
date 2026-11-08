# Deployed model on auto-renew-ON snapshots, by days before renewal (REAL evaluation)

Model lumen-temporal-catboost 1.0.0 (sha256 4f3fd0acc994…), untouched holdout from 05 Oct 2026, 27,024 snapshots where auto-renew is still on. 95% CIs: subscriber-clustered bootstrap. ROC-AUC 0.5 = random; lost revenue in the top 10% ≈ 10% for a random ranking.

| Days before renewal | Snapshots | Churned | Churn rate | ROC-AUC (95% CI) | PR-AUC (95% CI) | Lost revenue in top 10% (95% CI) |
|---|---|---|---|---|---|---|
| 30+ | 0 | 0 | — | — | — | — |
| 15–30 | 932 | 57 | 6.1% | 0.550 (0.450–0.655) | 0.077 (0.045–0.135) | 19.2% (5.9%–35.2%) |
| 7–14 | 4,123 | 391 | 9.5% | 0.597 (0.566–0.628) | 0.120 (0.105–0.139) | 14.4% (11.1%–18.1%) |
| 1–6 | 21,969 | 1,377 | 6.3% | 0.640 (0.624–0.655) | 0.096 (0.086–0.108) | 20.0% (18.0%–22.0%) |
| all | 27,024 | 1,825 | 6.8% | 0.640 (0.622–0.655) | 0.103 (0.093–0.115) | 18.5% (16.4%–20.5%) |

**30+ is empty by construction**: only the first day of a monthly period is 30+ days before its renewal, and a monthly period starting inside the 28-day holdout cannot have its renewal resolved before the data ends, so those snapshots are censored (excluded), not missing.
