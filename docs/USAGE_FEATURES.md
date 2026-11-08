# Optional usage-data support (branch `usage-features`)

App-usage events (sessions, app opens) are the signal the deployed churn model is missing: the Lumen dataset contains
none. This branch adds the plumbing to use them once real exports exist. It is **kept separate from the deployed
model**: nothing in the services reads usage data, and `services/inference/models/temporal_catboost` is unchanged.

## 1. Storage and loading

- **Table:** `postgres/init/004-usage-events.sql` creates `usage_events(user_id, event_name, occurred_at, …)`. It also
  stores `source` and `source_event_id`, and has a uniqueness constraint (user, event, time, source), so reloading the
  same export never duplicates rows. It is indexed by `(user_id, occurred_at)` for point-in-time lookups.
- **Loader:** `python -m ml.usage.loader EXPORT… [--database-url URL]` reads three formats, plain or gzipped. Rows
  without a user, event name or time are dropped and counted.
  - Amplitude Export API JSON lines: `user_id`, `event_type`, `event_time`
  - Firebase → BigQuery JSON lines: `user_id`, `event_name`, `event_timestamp` in microseconds
  - CSV: `user_id, event_name, occurred_at`
- **Matching:** the export's `user_id` must equal Adapty's `customer_user_id`. Subscribers come from local files only,
  no Adapty call: either the offline users plus the seeding run id (offline `u00042` = `lumen_<run>_00042`), or a cached
  `profiles_*.json`. The loader prints a match report (event users matched / unmatched, events matched, examples of
  unmatched ids). It writes to Postgres only when `--database-url` is given.

## 2. Point-in-time usage features (`ml/usage/features.py`)

| Feature | Definition |
|---|---|
| `sessions_7d`, `sessions_30d` | session events in [as_of_at − N days, as_of_at) |
| `days_since_last_session` | as_of_at − the last session before as_of_at; null if none yet |
| `sessions_trend_7d_delta` | sessions in the last 7 days − sessions in the 7 days before |
| `sessions_trend_7d_ratio` | (last 7 days + 1) / (previous 7 days + 1) |

- Only events **strictly before** `as_of_at` count. A session is an event named `session_start`, `app_open` or
  `[Amplitude] Start Session`.
- Subscribers with no usage data at all get **nulls, not zeros**, so "not tracked" never looks like "inactive".
- `tests/test_usage.py` (12 tests, hand-made fixture in `tests/fixtures/usage/`) checks:
  - all three formats, invalid rows and idempotent reloads;
  - the match report;
  - exact feature values for a known history;
  - that events **after** `as_of_at`, and **exactly at** it, are ignored (50 later events change nothing);
  - that non-session events don't count;
  - that untracked users get nulls.

## 3. REAL evaluation of the deployed model, auto-renew still ON, by days before renewal

`python -m ml.temporal_churn.eval_on_by_horizon`. Deployed artifact `lumen-temporal-catboost` 1.0.0 via its adapter;
untouched holdout from 5 Oct 2026; 27,024 snapshots with auto-renew on. 95% CIs use a subscriber-clustered bootstrap.

| Days before renewal | Snapshots | Churned | Churn rate | ROC-AUC (95% CI) | PR-AUC (95% CI) | Lost revenue in top 10% (95% CI) |
|---|---|---|---|---|---|---|
| 30+ | 0 | 0 | — | — | — | — |
| 15–30 | 932 | 57 | 6.1% | 0.550 (0.450–0.655) | 0.077 (0.045–0.135) | 19.2% (5.9%–35.2%) |
| 7–14 | 4,123 | 391 | 9.5% | 0.597 (0.566–0.628) | 0.120 (0.105–0.139) | 14.4% (11.1%–18.1%) |
| 1–6 | 21,969 | 1,377 | 6.3% | 0.640 (0.624–0.655) | 0.096 (0.086–0.108) | 20.0% (18.0%–22.0%) |
| all | 27,024 | 1,825 | 6.8% | 0.640 (0.622–0.655) | 0.103 (0.093–0.115) | 18.5% (16.4%–20.5%) |

- **30+ is empty by construction.** Only the first day of a monthly period is 30+ days before its renewal, and a
  monthly period starting inside the 28-day holdout cannot have its renewal resolved before the data ends. Those
  snapshots are censored.
- **Reading:** among subscribers who haven't switched auto-renew off, ranking is modest close to renewal (0.640) and
  weaker further out. At 15–30 days the CI includes 0.5, so there's no reliable early warning. This is the gap usage
  data would have to close.

## 4. SIMULATED – pipeline check, not a result

`python -m ml.usage.simulated_check`; full output in `ml/usage/reports/SIMULATED_usage_pipeline_check.md`.

> **SIMULATED – pipeline check, not a result.** All usage events here are synthetic. These numbers describe neither
> real users nor the deployed model, and must not be quoted as an improvement. The deployed model was not changed.

Synthetic Amplitude-format exports, for training and holdout subscribers plus 25 non-subscriber users, go through the
whole chain: loader → matching → point-in-time features → CatBoost with and without usage features (deployed
hyperparameters) → evaluation by days before renewal.

**SIMULATED – pipeline check, not a result** (auto-renew ON snapshots, ROC-AUC):

| Scenario | Days before renewal | Without usage | With usage | What a working pipeline should show |
|---|---|---|---|---|
| `null`: usage unrelated to churn | all | 0.640 | 0.643 | no meaningful change ✔ (CIs overlap in every bucket) |
| `signal`: churners' sessions fade over the last 14 days, injected from the known outcome | 1–6 | 0.640 | 0.737 | a gain where the signal exists ✔ |
| `signal` | 7–14 | 0.597 | 0.653 | a gain (the fade starts 14 days out) ✔ |
| `signal` | 15–30 | 0.550 | 0.514 | **no** gain: the signal does not exist yet ✔ |

**What the check shows** (pipeline mechanics only):
- The loader and matching work: in each scenario every event user is matched except the 25 decoy non-subscribers, and
  non-session decoy events are filtered out.
- Random usage adds nothing.
- An injected signal is picked up only in the windows where it exists. The 15–30-day bucket gets no gain, which is
  also what you'd expect if no future information leaks into the features.
- The size of the `signal` gain is set by how the simulation was built. It says nothing about how much real usage
  data would help.

## 5. What a real test needs

Real exports from the app's analytics (Amplitude, Firebase, or the backend), keyed by `customer_user_id`, covering
the same months as the subscription history. Then:
1. load with the loader;
2. add `USAGE_FEATURES` as a candidate set;
3. run the same ablation rule as the other candidates (all chronological folds better, holdout CI above 0).

Deploy only if it passes.
