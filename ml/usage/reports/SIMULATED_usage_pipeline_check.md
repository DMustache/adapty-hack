# SIMULATED – PIPELINE CHECK, NOT A RESULT

> **SIMULATED – pipeline check, not a result.** The Lumen dataset contains no usage data. All usage events below are synthetic, generated only to check that the usage pipeline works end to end. None of these numbers describes real users or the deployed model, and none may be quoted as a model improvement. The deployed model was not changed.

Holdout from 05 Oct 2026. Without usage = the deployed feature set; with usage = + sessions_7d, sessions_30d, days_since_last_session, sessions_trend_7d_delta, sessions_trend_7d_ratio. 95% CIs: subscriber-clustered bootstrap.

## SIMULATED – pipeline check, not a result: Scenario `null`: usage unrelated to churn (expected: no gain)

Generated 247,574 session + 74,484 decoy + 25 non-subscriber events. Loader kept 322,083 of 322,083 rows; matched 3,851 of 3,876 event users (25 unmatched, e.g. not_a_subscriber_0, not_a_subscriber_1).

**SIMULATED – pipeline check, not a result: auto-renew ON snapshots**

| Days before renewal | Variant | Snapshots | Churned | Churn rate | ROC-AUC (95% CI) | PR-AUC (95% CI) | Lost revenue in top 10% (95% CI) |
|---|---|---|---|---|---|---|---|
| 30+ | without usage (SIMULATED) | 0 | 0 | — | — | — | — |
| 30+ | with usage (SIMULATED) | 0 | 0 | — | — | — | — |
| 15–30 | without usage (SIMULATED) | 932 | 57 | 6.1% | 0.550 (0.445–0.648) | 0.077 (0.042–0.138) | 19.2% (4.8%–35.2%) |
| 15–30 | with usage (SIMULATED) | 932 | 57 | 6.1% | 0.571 (0.419–0.709) | 0.166 (0.046–0.365) | 12.6% (2.0%–29.4%) |
| 7–14 | without usage (SIMULATED) | 4,123 | 391 | 9.5% | 0.597 (0.563–0.625) | 0.120 (0.106–0.138) | 14.4% (11.2%–17.6%) |
| 7–14 | with usage (SIMULATED) | 4,123 | 391 | 9.5% | 0.596 (0.560–0.629) | 0.129 (0.112–0.153) | 14.2% (10.6%–17.3%) |
| 1–6 | without usage (SIMULATED) | 21,969 | 1,377 | 6.3% | 0.640 (0.626–0.657) | 0.096 (0.086–0.108) | 20.0% (18.0%–22.3%) |
| 1–6 | with usage (SIMULATED) | 21,969 | 1,377 | 6.3% | 0.642 (0.627–0.658) | 0.103 (0.091–0.120) | 20.4% (18.0%–22.7%) |
| all | without usage (SIMULATED) | 27,024 | 1,825 | 6.8% | 0.640 (0.621–0.658) | 0.103 (0.092–0.115) | 18.5% (16.3%–20.7%) |
| all | with usage (SIMULATED) | 27,024 | 1,825 | 6.8% | 0.643 (0.627–0.661) | 0.111 (0.096–0.126) | 20.4% (17.7%–22.9%) |

**SIMULATED – pipeline check, not a result: all snapshots**

| Days before renewal | Variant | Snapshots | Churned | Churn rate | ROC-AUC (95% CI) | PR-AUC (95% CI) | Lost revenue in top 10% (95% CI) |
|---|---|---|---|---|---|---|---|
| 30+ | without usage (SIMULATED) | 0 | 0 | — | — | — | — |
| 30+ | with usage (SIMULATED) | 0 | 0 | — | — | — | — |
| 15–30 | without usage (SIMULATED) | 947 | 72 | 7.6% | 0.644 (0.528–0.748) | 0.325 (0.180–0.463) | 33.1% (19.1%–45.7%) |
| 15–30 | with usage (SIMULATED) | 947 | 72 | 7.6% | 0.660 (0.521–0.785) | 0.381 (0.195–0.556) | 30.9% (14.3%–46.8%) |
| 7–14 | without usage (SIMULATED) | 4,159 | 427 | 10.3% | 0.631 (0.600–0.659) | 0.234 (0.190–0.278) | 26.1% (20.9%–31.7%) |
| 7–14 | with usage (SIMULATED) | 4,159 | 427 | 10.3% | 0.630 (0.597–0.661) | 0.245 (0.198–0.294) | 25.9% (20.0%–31.5%) |
| 1–6 | without usage (SIMULATED) | 22,914 | 2,322 | 10.1% | 0.787 (0.769–0.804) | 0.565 (0.531–0.598) | 50.0% (46.9%–53.4%) |
| 1–6 | with usage (SIMULATED) | 22,914 | 2,322 | 10.1% | 0.788 (0.772–0.806) | 0.568 (0.535–0.602) | 50.5% (47.6%–53.9%) |
| all | without usage (SIMULATED) | 28,020 | 2,821 | 10.1% | 0.767 (0.749–0.786) | 0.518 (0.486–0.547) | 45.6% (42.5%–48.6%) |
| all | with usage (SIMULATED) | 28,020 | 2,821 | 10.1% | 0.769 (0.751–0.790) | 0.522 (0.490–0.555) | 46.3% (43.3%–49.4%) |

## SIMULATED – pipeline check, not a result: Scenario `signal`: churners' sessions fade before renewal, injected from the known outcome (expected: artificial gain)

Generated 235,173 session + 70,766 decoy + 25 non-subscriber events. Loader kept 305,964 of 305,964 rows; matched 3,822 of 3,847 event users (25 unmatched, e.g. not_a_subscriber_0, not_a_subscriber_1).

**SIMULATED – pipeline check, not a result: auto-renew ON snapshots**

| Days before renewal | Variant | Snapshots | Churned | Churn rate | ROC-AUC (95% CI) | PR-AUC (95% CI) | Lost revenue in top 10% (95% CI) |
|---|---|---|---|---|---|---|---|
| 30+ | without usage (SIMULATED) | 0 | 0 | — | — | — | — |
| 30+ | with usage (SIMULATED) | 0 | 0 | — | — | — | — |
| 15–30 | without usage (SIMULATED) | 932 | 57 | 6.1% | 0.550 (0.447–0.642) | 0.077 (0.043–0.134) | 19.2% (6.7%–33.5%) |
| 15–30 | with usage (SIMULATED) | 932 | 57 | 6.1% | 0.514 (0.418–0.625) | 0.070 (0.040–0.114) | 11.5% (2.5%–20.6%) |
| 7–14 | without usage (SIMULATED) | 4,123 | 391 | 9.5% | 0.597 (0.567–0.627) | 0.120 (0.107–0.140) | 14.4% (11.4%–17.9%) |
| 7–14 | with usage (SIMULATED) | 4,123 | 391 | 9.5% | 0.653 (0.622–0.685) | 0.162 (0.139–0.192) | 18.3% (14.7%–22.6%) |
| 1–6 | without usage (SIMULATED) | 21,969 | 1,377 | 6.3% | 0.640 (0.626–0.657) | 0.096 (0.086–0.108) | 20.0% (17.9%–22.1%) |
| 1–6 | with usage (SIMULATED) | 21,969 | 1,377 | 6.3% | 0.737 (0.718–0.755) | 0.154 (0.131–0.185) | 29.1% (25.9%–32.5%) |
| all | without usage (SIMULATED) | 27,024 | 1,825 | 6.8% | 0.640 (0.621–0.657) | 0.103 (0.091–0.116) | 18.5% (16.7%–20.8%) |
| all | with usage (SIMULATED) | 27,024 | 1,825 | 6.8% | 0.719 (0.699–0.737) | 0.153 (0.131–0.184) | 25.4% (22.3%–28.6%) |

**SIMULATED – pipeline check, not a result: all snapshots**

| Days before renewal | Variant | Snapshots | Churned | Churn rate | ROC-AUC (95% CI) | PR-AUC (95% CI) | Lost revenue in top 10% (95% CI) |
|---|---|---|---|---|---|---|---|
| 30+ | without usage (SIMULATED) | 0 | 0 | — | — | — | — |
| 30+ | with usage (SIMULATED) | 0 | 0 | — | — | — | — |
| 15–30 | without usage (SIMULATED) | 947 | 72 | 7.6% | 0.644 (0.537–0.750) | 0.325 (0.186–0.472) | 33.1% (18.7%–46.8%) |
| 15–30 | with usage (SIMULATED) | 947 | 72 | 7.6% | 0.615 (0.499–0.735) | 0.315 (0.169–0.475) | 28.5% (15.9%–42.6%) |
| 7–14 | without usage (SIMULATED) | 4,159 | 427 | 10.3% | 0.631 (0.598–0.662) | 0.234 (0.189–0.276) | 26.1% (20.6%–31.5%) |
| 7–14 | with usage (SIMULATED) | 4,159 | 427 | 10.3% | 0.683 (0.650–0.712) | 0.282 (0.235–0.327) | 29.4% (23.5%–34.4%) |
| 1–6 | without usage (SIMULATED) | 22,914 | 2,322 | 10.1% | 0.787 (0.769–0.804) | 0.565 (0.531–0.595) | 50.0% (47.4%–53.0%) |
| 1–6 | with usage (SIMULATED) | 22,914 | 2,322 | 10.1% | 0.844 (0.829–0.858) | 0.617 (0.585–0.647) | 54.8% (51.8%–57.7%) |
| all | without usage (SIMULATED) | 28,020 | 2,821 | 10.1% | 0.767 (0.749–0.784) | 0.518 (0.484–0.546) | 45.6% (42.3%–48.4%) |
| all | with usage (SIMULATED) | 28,020 | 2,821 | 10.1% | 0.818 (0.802–0.833) | 0.566 (0.532–0.596) | 49.3% (46.3%–51.9%) |

