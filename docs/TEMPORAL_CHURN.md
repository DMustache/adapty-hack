# Temporal churn model (CatBoost) — Smart Retention Offers

Predicts **failure to renew at the next eligible renewal event** for active weekly/monthly subscribers, from
**point-in-time snapshots**, so the risk of each subscriber can be followed as it evolves. Data: the Adapty
hackathon *Lumen* offline dataset, which is **synthetic**. All numbers below were produced by
`python -m ml.temporal_churn.train` and `python -m ml.temporal_churn.ablation` on 2026-11-08.

Training lives in `ml/temporal_churn/` (researcher side). The services only load the exported, checksummed artifact
through an adapter, as `docs/MODEL_HANDOFF.md` requires. Routes are unchanged; the contract gained optional fields.

## 1. Snapshots and labels

| | |
|---|---|
| Unit | one active weekly/monthly **paid** subscriber at an instant `as_of_at` inside a paid period |
| Cadence | daily (weekly plans) or every 3 days (monthly plans), from the payment until the renewal is due |
| `renewal_due_at` | end of the current paid period = the next eligible renewal event |
| Label | `churn = 1` if that renewal does not happen (voluntary cancellation, billing failure or refund), else 0 |
| Observation cutoff | the last **observed** event in the data, 2026-11-03 00:07 UTC (never a scheduled `expires_at`) |
| Censoring | a snapshot is labelled only if its renewal was resolved ≥ 1 day before the cutoff; later ones are scored but never trained or evaluated on (11,717 of 109,599 snapshots) |
| Leakage guard | every feature uses events with timestamp ≤ `as_of_at`; a test rewrites all later events and checks earlier snapshots are unchanged |

**Temporal features:**
- `tenure_days`
- `renewal_count`
- `days_until_renewal`
- `days_since_last_payment`
- `historical_renewal_success_rate`
- `billing_issues_last_30d`
- `days_since_install`
- `auto_renew_off` and `days_since_auto_renew_off` (status as of the snapshot)

**Static features:**
- plan, renewal price, price tier, platform, country, acquisition channel, app version, placement, paywall flow, trial start
- `onboarding_goal`, `push_opt_in`, `ai_edits_first_day`, `photos_imported`

**Data limits.** No subscriber ever re-subscribes, and a chain ends at its first failed renewal. So
`historical_renewal_success_rate` is always 1.0 (or null before the first renewal). Billing issues are only recorded
at the final failed renewal, so `billing_issues_last_30d` is always 0 at snapshot time. Both are kept so the model
works on real data, but they carry no signal here. There is **no usage/engagement history** (sessions, app opens,
feature use) in any dataset.

## 2. Evaluation (temporal holdout)

- **Train:** 61,528 snapshots (2,412 subscribers), as-of 6 Jul – 4 Oct. Every training renewal resolved before 5 Oct.
- **Untouched holdout:** 28,020 snapshots (2,130 subscribers), as-of 5 – 31 Oct, churn 10.1%.
- **Hyperparameters:** chronological forward-chaining CV inside the training period (purged), no random CV. The
  first grid (500 rounds) overfitted: static and behaviour models scored worse than a constant. The grid was widened
  to regularized settings, still chosen by CV only. Every model picked depth 3, 100 rounds, learning rate 0.03, L2 10.

| CatBoost model | Brier (constant at test rate) | Log loss | PR-AUC | ROC-AUC | ECE | Calib. slope / int. | Lost revenue in top 10% / 20% |
|---|---|---|---|---|---|---|---|
| static (baseline) | 0.0911 (0.0905) | 0.3290 | 0.118 | 0.552 | 0.034 | 1.77 / +1.15 | 14.2% / 27.7% |
| temporal_behaviour (no auto-renew status) | 0.0907 (0.0905) | 0.3273 | 0.118 | 0.556 | 0.023 | 1.11 / −0.02 | 15.5% / 27.9% |
| **temporal (deployed)** | **0.0601** (0.0905) | **0.2337** | **0.518** | **0.767** | **0.016** | 1.38 / +0.63 | **45.6% / 56.7%** |

*Constant at test rate* = predicting the holdout's own churn rate for everyone, an optimistic benchmark no real model
can know in advance.

**Brier improvement** (subscriber-clustered bootstrap, 95% CI; positive = second model better):
- temporal vs static: **+0.0310 (+0.0279 to +0.0340)**
- temporal_behaviour vs static: +0.0003 (+0.0001 to +0.0005)
- temporal vs temporal_behaviour: +0.0306 (+0.0274 to +0.0337)

**How risk evolves** (mean predicted risk on the holdout, temporal model):

| Days until renewal | 7 | 6 | 5 | 4 | 3 | 2 | 1 |
|---|---|---|---|---|---|---|---|
| Subscribers who renewed | 0.124 | 0.106 | 0.107 | 0.093 | 0.071 | 0.061 | 0.053 |
| Subscribers who churned | 0.125 | 0.216 | 0.257 | 0.393 | 0.532 | 0.611 | 0.748 |

Ranking quality grows as the renewal approaches. PR-AUC is 0.20 at 5–8 days out, 0.40 at 3–5 days, 0.62 at 2–3 days
and **0.80** in the last day. The static model stays flat at about 0.13 for both groups.

**Calibration:** the top risk decile is accurate (predicted 0.439, observed 0.436). Lower deciles over-predict by
about 2 points, because churn fell from about 11% in training to 10% in the holdout. Re-calibrate on recent data
before using the probabilities as exact rates.

**Onboarding / first-day attributes** (`ai_edits_first_day`, `photos_imported`, `onboarding_goal`, `push_opt_in`): all
models include them. Removing them makes every model worse:

| Model | Brier without → with | Gain (95% CI) | PR-AUC without → with |
|---|---|---|---|
| static | 0.09146 → 0.09106 | +0.00040 (+0.00014 to +0.00067) | 0.109 → 0.118 |
| temporal_behaviour | 0.09171 → 0.09074 | +0.00096 (+0.00066 to +0.00127) | 0.103 → 0.118 |
| temporal | 0.06089 → 0.06011 | +0.00078 (+0.00061 to +0.00095) | 0.509 → 0.518 |

**Reading the results honestly:**
- The time-aware gain comes almost entirely from **auto-renew status over time**: seeing that a subscriber has switched
  it off, and since when.
- Tenure, renewal count and days to renewal add only a tiny, significant improvement on their own (+0.0003 Brier).
- Without engagement data, churn is barely predictable before a user cancels: about 0.55 ROC-AUC for the models
  without auto-renew status.
- The temporal model's strength is **detecting and tracking risk as cancellations happen**, early enough before the
  renewal to act.

## 3. Serving, storage and dashboards

- **Artifact:** `services/inference/models/temporal_catboost/` holds `model.cbm` (CatBoost format, no pickle),
  `model.cbm.sha256` and `metadata.json` (feature order, JSON input schema, metrics, provenance). The adapter
  `services/inference/app/adapters/temporal_catboost.py` refuses to load on a checksum mismatch. It is registered as
  `lumen-temporal-catboost` next to the mock, and only if the artifact is present.
- **Contract:** `ChurnPredictionRequest` / `ChurnPredictionResult` gained **optional** `as_of_at`, `renewal_due_at`
  (timezone required; due ≥ as-of) and `renewal_price_usd` (> 0). Old payloads stay valid. Schemas were regenerated
  with `scripts/export_schemas.py`.
- **Storage:** `postgres/init/003-temporal-predictions.sql` adds the three columns and two views:
  - `churn_risk_trajectory`: every prediction, with the previous probability, the change, days until renewal and
    expected revenue at risk (probability × renewal price);
  - `churn_risk_current`: latest prediction per subscriber and model.

  Predictions stay immutable: each new snapshot is a new row. Analytics stores the new fields and serves
  `GET /v1/metrics/churn-trajectory?user_id=…[&app_id=…&model_id=…]`.
- **Grafana:** new dashboard *Churn Risk Over Time* (`grafana/dashboards/churn-risk-trajectory.json`), with model and
  subscriber selectors. Panels:
  - current churn probability;
  - expected next-renewal revenue at risk;
  - current risk by subscriber;
  - risk trajectory;
  - change since the previous prediction;
  - mean risk over time;
  - largest risk increases.

  The existing dashboard is unchanged.

## 4. Run it end to end (not run here: Docker is not installed on the development machine)

```bash
# fresh database volume, so the init scripts (incl. 003) run; or apply 003 by hand to an existing volume:
#   docker compose exec -T postgres psql -U adapty_demo -d adapty_demo < postgres/init/003-temporal-predictions.sql
docker compose down -v && docker compose up --build -d

# replay recent snapshots (50 subscribers, last 35 days = 1,750 predictions) through /v1/predict
python scripts/score_temporal_snapshots.py --data-dir /path/to/adapty-seed-data-hack/data/offline

# then open Grafana at http://127.0.0.1:3000 → "Churn Risk Over Time" (time range: last 120 days)
```

Retrain: `python -m ml.temporal_churn.train --data-dir …`, then `python -m ml.temporal_churn.ablation` and
`python -m ml.temporal_churn.make_fixture` (the adapter test pins the new artifact's outputs).
Tests: `python -m pytest -q`. Snapshot and adapter tests skip cleanly without the dataset or artifact.

## 5. Limitations

- **Synthetic data:** effects were generated, not observed from real users.
- **No engagement history:** a real deployment should add sessions, feature use and paywall views from Adapty
  events or app analytics.
- **Cadence:** snapshots are daily (weekly plans) or every 3 days (monthly). Annual plans are out of scope: no
  renewal is observable in 120 days.
- **Calibration drift:** the training-to-holdout drop in churn causes slight over-prediction at low risk.
- **No causal effect:** the model predicts risk, not what a discount would do. Retention offers still need
  randomized tests (`/v1/retention/plan`).
