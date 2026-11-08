# Usage (Firebase / Amplitude) features in the churn pipeline

App-usage events (sessions, app opens) are the signal the deployed churn model is missing: the Lumen dataset contains
none. The pipeline below loads real exports when they exist, builds point-in-time engagement features, trains a churn
model **with** them next to the **unchanged** deployed 23-feature model, and serves it as an **optional second model**.

```text
Amplitude / Firebase / CSV export ──► ml/usage/loader.py ──► usage_events (Postgres, optional)
                                            │ match on customer_user_id
                                            ▼
point-in-time snapshots (ml/temporal_churn/snapshots.py) + add_usage_features()  (events strictly before as_of_at)
                                            ▼
ml/temporal_churn/train_usage.py: baseline "temporal" (23) vs "temporal_usage" (23 + 8), same split/CV/seed
                                            ▼ acceptance rule + --export
services/inference/models/temporal_usage_catboost/ ──► TemporalUsageCatBoostAdapter ──► POST /v1/predict
                                                         (model_id lumen-temporal-usage-catboost)
```

**The deployed model is not changed.** `lumen-temporal-catboost` 1.0.0 keeps its 23 features, pinned checksum and
default role everywhere (analytics, Retention offers, scoring script). The usage model is used only when a caller asks
for it by `model_id`, and only if its artifact is installed.

## 1. Storage and loading

- **Table:** `postgres/init/007-usage-events.sql` creates `usage_events(user_id, event_name, occurred_at, source,
  source_event_id, …)` with a uniqueness constraint (user, event, time, source), so reloading an export never
  duplicates rows; indexed by `(user_id, occurred_at)`. Existing volume: run the file once by hand.
- **Loader:** `python -m ml.usage.loader EXPORT… [--database-url URL]`, plain or gzipped:
  - Amplitude Export API JSON lines: `user_id`, `event_type`, `event_time`
  - Firebase → BigQuery JSON lines: `user_id`, `event_name`, `event_timestamp` (microseconds)
  - CSV: `user_id, event_name, occurred_at`
  Rows without a user, event or time are dropped and counted. `read_events(database_url)` reads the table back.
- **Matching:** the export's `user_id` must equal Adapty's `customer_user_id`. Subscribers come from local files only
  (offline users + seeding run id, or a cached `profiles_*.json`); no Adapty calls. A match report is printed.

## 2. Point-in-time features (`ml/usage/features.py`)

| Feature | Definition |
|---|---|
| `sessions_7d`, `sessions_14d`, `sessions_30d` | session events in [as_of_at − N days, as_of_at) |
| `days_since_last_session` | as_of_at − last session before as_of_at (null if none yet) |
| `days_since_last_activity` | as_of_at − last event of **any** kind before as_of_at |
| `sessions_trend_7d_delta` | sessions in the last 7 days − sessions in the 7 days before |
| `sessions_trend_7d_ratio` | (last 7 days + 1) / (previous 7 days + 1) |
| `session_rate_7d_vs_30d` | (sessions_7d + 1) / (sessions_30d × 7/30 + 1): < 1 = usage fading |

- **No leakage:** only events **strictly before** `as_of_at` count, including for deciding whether a subscriber is
  tracked at all. A subscriber whose first event comes after `as_of_at` is still "untracked" at that snapshot.
- **Optional:** subscribers without usage history get **nulls, not zeros**, so "not tracked" never looks like
  "inactive". If you know when tracking started (e.g. SDK rollout), pass `tracked_since`; tracked-but-inactive
  subscribers then get zero sessions.
- A session is an event named `session_start`, `app_open` or `[Amplitude] Start Session` (`SESSION_EVENTS`).

## 3. Training (`ml/temporal_churn/train_usage.py`)

```bash
python -m ml.temporal_churn.train_usage --usage export1.json.gz export2.json.gz [--profiles profiles.json] [--export]
python -m ml.temporal_churn.train_usage --database-url postgresql://… [--export]
```

- Both models: CatBoost, same snapshots, labels, 28-day temporal holdout, chronological CV grid and seed as
  `train.py`. Baseline = the deployed 23 features; candidate = 23 + 8 usage features.
- **Acceptance rule** (same as every earlier feature experiment): lower Brier in **every** chronological fold **and**
  a subscriber-clustered bootstrap 95% CI of the holdout Brier gain above zero. The report
  (`ml/temporal_churn/reports/usage_evaluation.md`) also shows usage coverage and Brier for snapshots with / without
  usage history.
- `--export` writes `services/inference/models/temporal_usage_catboost/` (model.cbm, SHA-256, metadata with the
  baseline's id/version/checksum, the verdict, and which features are optional). Exporting never deploys anything
  by itself and never touches the baseline artifact (a test checks its checksum before and after).
- **Simulated data guard:** with `--simulated` or events whose source is `simulated`, every output is labelled
  "SIMULATED – pipeline check, not a result", reports are prefixed `SIMULATED_`, and the model can only be exported
  to an explicit `--artifact-dir`, never to the service folder.

## 4. Inference and scoring

- `services/inference/app/adapters/temporal_usage_catboost.py` loads the artifact only if installed (or
  `TEMPORAL_USAGE_MODEL_DIR` is set). It refuses an artifact whose checksum doesn't match, whose first 23 features
  differ from the deployed model's (names or order), or whose usage features aren't optional and nullable.
- Request schema: the 23 baseline features are required; usage features may be omitted or `null` (same prediction
  either way). Unknown features are rejected. The usage model gets the same UTC `as_of_at` / `renewal_due_at` checks
  as the deployed temporal model.
- Scoring: `python scripts/score_temporal_snapshots.py --model-id lumen-temporal-usage-catboost --usage EXPORT…`
  (or `--usage-database-url URL`). Without `--model-id` it behaves exactly as before.

## 5. Tests

- `tests/test_usage.py` (15): formats, invalid rows, idempotent reload, match report, exact feature values incl. the
  new ones, events after/at `as_of_at` ignored, point-in-time tracking status, `tracked_since`, untracked → nulls.
- `tests/test_usage_pipeline.py` (11), on **SIMULATED** subscribers and sessions: feature set = deployed 23 + usage;
  no usage source → all nulls, baseline columns untouched; future events never change earlier snapshots; training
  report labelled SIMULATED with no accuracy claim; simulated model can't be exported to the service folder; exported
  metadata; adapter scores with, without and with null usage (omitted == null); tampered artifacts rejected; the API
  serves both models side by side and keeps the deployed schema strict; scoring script builds usage requests.

## 6. SIMULATED – pipeline check, not a result

> **SIMULATED – pipeline check, not a result.** All usage events below are synthetic. These numbers describe neither
> real users nor real accuracy and must not be quoted as an improvement. The deployed model was not changed.

`python -m ml.usage.simulated_check` on the full Lumen subscription data (≈ 20 minutes). Synthetic sessions (plus decoy
non-session events) are written as an Amplitude export, read back by the real loader, matched, turned into
point-in-time features and trained through `train_usage` (same split, grid and rule as the deployed model). About 20%
of subscribers get no usage at all, to exercise the null path. Reports:
`ml/temporal_churn/reports/SIMULATED_usage_pipeline_check_{null,signal}.md`.

| Scenario | Usage coverage (test) | Brier baseline → usage | Gain (95% CI) | Every fold better | Passes rule | A working pipeline should show |
|---|---|---|---|---|---|---|
| `null`: usage unrelated to churn | 79.1% | 0.0601 → 0.0601 | −0.00000 (−0.00004 to +0.00004) | no | **no** | no gain ✔ |
| `signal`: churners' sessions fade over the last 14 days (injected from the known outcome) | 79.0% | 0.0601 → 0.0588 | +0.00130 (+0.00088 to +0.00169) | yes | yes | a gain, only where the signal was planted ✔ |

What this shows, and only this:
- **Loading and matching work:** 263,616 / 245,521 synthetic events, all 3,057 / 3,081 event users matched.
- **Random usage adds nothing**, so the pipeline isn't inventing signal (no leakage).
- **An injected signal is picked up**, and only for subscribers who have usage: in `signal`, Brier for snapshots
  *with* usage drops 0.0586 → 0.0569, while snapshots *without* usage stay exactly 0.0658 → 0.0658. Nulls are handled
  as "no information", not as "inactive".
- The size of the `signal` gain is set by how the simulation was built. It says **nothing** about how much real
  Firebase / Amplitude data would help; that needs real exports and the same rule.

## 7. What a real test needs

Real exports (Amplitude, Firebase or backend), keyed by `customer_user_id`, covering the same months as the
subscription history. Then run `train_usage` on them. Deploy (switch callers to `lumen-temporal-usage-catboost`)
only if it passes the acceptance rule; otherwise keep the 23-feature model.
