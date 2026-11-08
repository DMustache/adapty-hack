# Revenue-to-date candidate features: ablation

Each group is added to the deployed temporal model (same hyperparameters, snapshots, holdout). Helps = lower Brier in every chronological CV fold AND holdout gain with 95% CI above 0. `cancellation_reason` is never used. Already in the deployed model, so not re-added: placement, flow, acquisition_channel, app_version.

Deployed temporal set: holdout Brier 0.06011, PR-AUC 0.518.

| Group | Varies in this data | CV folds improved | Holdout Brier gain (95% CI) | PR-AUC | Helps |
|---|---|---|---|---|---|
| cumulative_net_revenue | cumulative_net_revenue_usd | 0/3 | -0.00004 (-0.00007 to +0.00001) | 0.518 | no |
| revenue_per_subscribed_day | revenue_per_subscribed_day | 0/3 | +0.00001 (-0.00003 to +0.00004) | 0.518 | no |
| all_together | cumulative_net_revenue_usd, revenue_per_subscribed_day | 0/3 | -0.00002 (-0.00006 to +0.00003) | 0.518 | no |

## Ranking among subscribers whose auto-renew is still ON

Holdout snapshots with auto-renew on: 27,024, churn 6.8%. ROC-AUC 0.5 = random ranking.

| Model | ROC-AUC (95% CI) | PR-AUC | Brier (constant) | Lost revenue in top 10% / 20% |
|---|---|---|---|---|
| temporal (deployed) | 0.640 (0.623–0.660) | 0.103 | 0.06232 (0.06297) | 18.5% / 35.7% |
| temporal + cumulative_net_revenue | 0.638 (0.619–0.656) | 0.102 | 0.06235 (0.06297) | 18.2% / 35.8% |
| temporal + revenue_per_subscribed_day | 0.638 (0.619–0.659) | 0.103 | 0.06231 (0.06297) | 18.9% / 35.2% |
| temporal + all_together | 0.637 (0.619–0.655) | 0.102 | 0.06234 (0.06297) | 18.5% / 34.9% |
| static | 0.545 (0.513–0.575) | 0.078 | 0.06684 (0.06297) | 10.8% / 24.3% |
| temporal_behaviour | 0.568 (0.539–0.596) | 0.083 | 0.06587 (0.06297) | 15.4% / 24.5% |
| trained on auto-renew-ON only, all candidate features | 0.637 (0.617–0.656) | 0.103 | 0.06233 (0.06297) | 18.6% / 35.1% |
