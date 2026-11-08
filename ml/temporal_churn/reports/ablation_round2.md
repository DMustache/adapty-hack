# Round-2 candidate features: ablation

Each group is added to the deployed temporal model (same hyperparameters, snapshots, holdout). Helps = lower Brier in every chronological CV fold AND holdout gain with 95% CI above 0. `cancellation_reason` is never used. Already in the deployed model, so not re-added: placement, flow, acquisition_channel, app_version.

Deployed temporal set: holdout Brier 0.06011, PR-AUC 0.518.

| Group | Varies in this data | CV folds improved | Holdout Brier gain (95% CI) | PR-AUC | Helps |
|---|---|---|---|---|---|
| switch_off_timing | auto_renew_off_period_fraction, leaving_window_elapsed | 2/3 | +0.00001 (-0.00002 to +0.00005) | 0.518 | no |
| ab_test | ab_test | 1/3 | -0.00003 (-0.00006 to +0.00000) | 0.517 | no |
| first_offer | first_offer | 1/3 | -0.00002 (-0.00006 to +0.00002) | 0.518 | no |
| locale | locale | 1/3 | -0.00003 (-0.00006 to +0.00000) | 0.517 | no |
| install_time | install_hour_utc, install_weekday_utc | 1/3 | -0.00000 (-0.00004 to +0.00004) | 0.518 | no |
| days_install_to_first_purchase | days_install_to_first_purchase | 0/3 | +0.00000 (-0.00004 to +0.00004) | 0.517 | no |
| cohort_churn_rate_channel | cohort_churn_rate_channel | 0/3 | +0.00001 (-0.00003 to +0.00006) | 0.519 | no |
| cohort_churn_rate_country | cohort_churn_rate_country | 0/3 | -0.00004 (-0.00008 to -0.00001) | 0.517 | no |
| cohort_churn_rate_paywall | cohort_churn_rate_paywall | 0/3 | -0.00000 (-0.00004 to +0.00004) | 0.518 | no |
| all_round2_features | auto_renew_off_period_fraction, leaving_window_elapsed, ab_test, first_offer, locale, install_hour_utc, install_weekday_utc, days_install_to_first_purchase, cohort_churn_rate_channel, cohort_churn_rate_country, cohort_churn_rate_paywall | 0/3 | -0.00001 (-0.00006 to +0.00003) | 0.518 | no |

## Ranking among subscribers whose auto-renew is still ON

Holdout snapshots with auto-renew on: 27,024, churn 6.8%. ROC-AUC 0.5 = random ranking.

| Model | ROC-AUC (95% CI) | PR-AUC | Brier (constant) | Lost revenue in top 10% / 20% |
|---|---|---|---|---|
| temporal (deployed) | 0.640 (0.622–0.657) | 0.103 | 0.06232 (0.06297) | 18.5% / 35.7% |
| temporal + switch_off_timing | 0.640 (0.623–0.656) | 0.102 | 0.06231 (0.06297) | 18.9% / 35.8% |
| temporal + ab_test | 0.638 (0.621–0.655) | 0.102 | 0.06235 (0.06297) | 18.7% / 34.5% |
| temporal + first_offer | 0.639 (0.621–0.657) | 0.103 | 0.06234 (0.06297) | 18.8% / 35.6% |
| temporal + locale | 0.638 (0.622–0.656) | 0.102 | 0.06235 (0.06297) | 18.7% / 34.5% |
| temporal + install_time | 0.640 (0.625–0.659) | 0.102 | 0.06232 (0.06297) | 19.3% / 35.5% |
| temporal + days_install_to_first_purchase | 0.638 (0.619–0.656) | 0.102 | 0.06232 (0.06297) | 17.9% / 36.3% |
| temporal + cohort_churn_rate_channel | 0.639 (0.622–0.658) | 0.104 | 0.06230 (0.06297) | 19.5% / 35.3% |
| temporal + cohort_churn_rate_country | 0.637 (0.618–0.654) | 0.103 | 0.06236 (0.06297) | 18.0% / 34.9% |
| temporal + cohort_churn_rate_paywall | 0.639 (0.622–0.658) | 0.103 | 0.06232 (0.06297) | 19.3% / 35.6% |
| temporal + all_round2_features | 0.638 (0.617–0.656) | 0.103 | 0.06233 (0.06297) | 18.3% / 35.5% |
| static | 0.545 (0.516–0.576) | 0.078 | 0.06684 (0.06297) | 10.8% / 24.3% |
| temporal_behaviour | 0.568 (0.541–0.597) | 0.083 | 0.06587 (0.06297) | 15.4% / 24.5% |
| trained on auto-renew-ON only, all round-2 features | 0.637 (0.618–0.655) | 0.102 | 0.06232 (0.06297) | 18.2% / 35.5% |
