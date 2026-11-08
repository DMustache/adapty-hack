# Subscription-history features: ablation

Each group is added to the deployed temporal model (same hyperparameters, snapshots, holdout). Helps = lower Brier in every chronological CV fold AND holdout gain with 95% CI above 0. `cancellation_reason` is never used.

Deployed temporal set: holdout Brier 0.06011, PR-AUC 0.518.

| Group | Varies in this data | CV folds improved | Holdout Brier gain (95% CI) | PR-AUC | Helps |
|---|---|---|---|---|---|
| auto_renew_toggles | auto_renew_toggles, days_since_auto_renew_change | 0/3 | -0.00001 (-0.00005 to +0.00002) | 0.517 | no |
| plan_changes | no (constant) | 0/3 | +0.00000 (+0.00000 to +0.00000) | 0.518 | no |
| first_full_price_renewal_after_offer | first_renewal_after_offer, paid_periods_since_offer | 0/3 | +0.00001 (-0.00004 to +0.00005) | 0.518 | no |
| price_vs_country_median | no (constant) | 0/3 | +0.00000 (+0.00000 to +0.00000) | 0.518 | no |
| prior_refunds | no (constant) | 0/3 | +0.00000 (+0.00000 to +0.00000) | 0.518 | no |
| all_history_features | auto_renew_toggles, days_since_auto_renew_change, first_renewal_after_offer, paid_periods_since_offer | 1/3 | -0.00001 (-0.00004 to +0.00002) | 0.518 | no |
