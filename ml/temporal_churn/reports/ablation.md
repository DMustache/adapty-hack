# Ablation: onboarding / first-day attributes

Removed: ai_edits_first_day, photos_imported, onboarding_goal, push_opt_in. Same hyperparameters, snapshots and temporal holdout. Brier gain = Brier(without) − Brier(with); positive means the attributes help (subscriber-clustered bootstrap 95% CI).

| Model | Brier without → with | Brier gain (95% CI) | PR-AUC without → with |
|---|---|---|---|
| static | 0.09146 → 0.09106 | +0.00040 (+0.00014 to +0.00067) | 0.109 → 0.118 |
| temporal_behaviour | 0.09171 → 0.09074 | +0.00096 (+0.00066 to +0.00127) | 0.103 → 0.118 |
| temporal | 0.06089 → 0.06011 | +0.00078 (+0.00061 to +0.00095) | 0.509 → 0.518 |
