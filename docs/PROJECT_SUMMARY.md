# Smart Retention Offers: complete project summary

*Adapty hackathon · state of `main` · 2026-11-08*

This document summarises everything built: the data findings, the **Discount Advisor**, the **temporal churn model**
and its experiments, **usage-data support**, the work in the **live Adapty account**, and how to run, test and extend it
all. Detailed write-ups are linked in each section; every number here comes from the generated reports.

---

## 1. What exists and where

| Component | Where | Purpose | Status |
|---|---|---|---|
| Smart Retention system | `services/`, `postgres/`, `grafana/`, `shared/` (team) | FastAPI inference + analytics, PostgreSQL, Grafana | Team-built; extended below |
| **Discount Advisor** | `discount_advisor/` | Decides which discount is worth **testing** (if any) | Complete |
| **Temporal churn model** | `ml/temporal_churn/`, `services/inference/models/temporal_catboost/` | Predicts non-renewal at the next renewal and how risk evolves | Deployed (v1.0.0) |
| Churn API, storage, dashboard | `services/inference/app/adapters/temporal_catboost.py`, `postgres/init/003-…`, `grafana/dashboards/churn-risk-trajectory.json` | Serve, store and show repeated predictions | Built and tested; end-to-end Docker run not yet done |
| **Usage-data support** | `ml/usage/`, `postgres/init/004-usage-events.sql` | Load Amplitude/Firebase/CSV usage, point-in-time features | Built and tested; **not** used by the deployed model |
| Live Adapty checks and seeding scripts | `discount_advisor/adapty_live.py`, `seed_50k.py`, `adapty_experiment.py` | Verify, seed and experiment in the Adapty account | Done |

Detailed docs:
- `discount_advisor/PROJECT_OVERVIEW.md`, `discount_advisor/DISCOUNT_FORMULA.md`, `discount_advisor/DEMO_SCRIPT.md`
- `docs/TEMPORAL_CHURN.md`
- `docs/USAGE_FEATURES.md`
- `docs/MODEL_HANDOFF.md` (the team's model spec)

---

## 2. The data and what it can tell us

The Adapty hackathon *Lumen* app is **synthetic**: 50,000 installs (5 Jul – 2 Nov 2026) and 29,794 receipts, of which
9,722 users paid. The observation cutoff is the last *observed* event, **3 Nov 2026 00:07 UTC**; scheduled
`expires_at` dates run to Nov 2027 and are never used as a cutoff.

**Contained:**
- one price per product per country;
- trials, renewals, cancellations, refunds, billing issues;
- the paywall placement/flow each user saw;
- three randomized A/B tests;
- first-day attributes (`ai_edits_first_day`, `photos_imported`, onboarding goal, push opt-in).

**Missing:**
- **any discount exposure or within-market price variation**, so price sensitivity can't be learned;
- **any usage/engagement history** (sessions, app opens);
- annual renewals (only ~17 weeks of history);
- costs.

**Confounding trap:** cheaper countries convert *less* (India at 35% of the US price: 8.3%; US: 26.6%). Country drives
both price and willingness to pay, so this is not a discount-response estimate.

**Data semantics (all checked by tests):**
- one payment chain per user, contiguous receipts, no re-subscriptions;
- trials are $0 receipt #0;
- refunds hit only the last receipt;
- the first paid receipt comes ≤ 9 days after install, hence a **14-day conversion window**.

---

## 3. Discount Advisor (`discount_advisor/`)

A Streamlit app. Every number is labelled **DATA** (measured), **CALCULATED** (exact arithmetic) or **ASSUMED** (your
input). It recommends an **experiment**, never a "proven best discount".

**How a discount is picked** (`DISCOUNT_FORMULA.md`):
1. **Exact break-even.** A payer's value after the discount is `v_d = (1−d)·a + (1−a)·(1−k·d)`, where `a` = share of
   revenue the discount touches and `k` = extra churn when full price returns. Break-even lift `L* = (1/v_d − 1)/ρ`.
   Example: 35% off on onboarding needs conversion to rise from 16.8% to 22.5%.
2. **Assumed response.** You state how much a 20% discount would lift conversion (low / likely / high). A
   diminishing-returns curve with a market ceiling is simulated 4,000 times.
3. **Testable?** A discount is *worth testing* only if it beats full price in ≥ 50% of scenarios **and** a 50/50 test
   can detect its break-even lift within 8 weeks. Otherwise: keep full price.

**Results (default settings, 12-month horizon, discount on the first paid payment):**

| Audience | Recommendation |
|---|---|
| onboarding, winning weekly-first paywall (`onb_weekly`) | **test 40% off**: break-even 36.7%, 456 users/arm, ≈ 3 weeks |
| onboarding, both paywalls (blend; the app warns) | test 35% off: break-even 34.2%, 751 users/arm, ≈ 3 weeks |
| main | **test 30% off**: break-even 30.9%, 753 users/arm, ≈ 4 weeks |
| ai_limit_reached, settings_upgrade | keep full price (annual plans: the discount hits all revenue) |
| win_back | keep full price (116 installs/week: no test fits in 8 weeks; 52% of value extrapolated) |

**Finding from the real randomized A/B tests in the data** (balanced arms, so these are causal effects):

| Test | Conversion | Revenue per install |
|---|---|---|
| Onboarding: annual trial → **weekly first** | 11.3% → 22.3% (+96%) | +106% |
| Settings: upgrade → **lifetime anchor** | 17.5% → 25.0% (+43%) | +51% |
| Main (US/CA): 3 plans → **lifetime anchor** | 23.9% → 30.2% (+26%) | +37% |

Changing the offer's **structure** beat any discount at full price. So: **test paywall structure first, discounts on the
winning paywall.**

**Tabs:**
- Recommendation
- Sensitivity
- Compare segments
- Randomized tests
- Baselines
- Data reality check
- Live Adapty
- Method

**Tests:** 148 core (+24 live checks skipped by default) and 40 end-to-end app tests, all passing.

---

## 4. Churn prediction

### 4.1 First comparison (single snapshot per renewal, `churn_model/` prototype, local only)

The comparison covered:
- a plan-only baseline;
- Logistic Regression, LightGBM, CatBoost;
- an equal-weight blend;
- a stacking ensemble.

It used chronological CV only, an untouched holdout, and the rule "simplest model with a reproducible improvement".
- **Before cancellation** (attributes only): **no model reproducibly beat the plan-only baseline**.
- **With auto-renew status:** CatBoost selected; stacking did not win.

This led to the temporal model.

### 4.2 Temporal churn model (deployed, `docs/TEMPORAL_CHURN.md`)

**Snapshots:**
- point-in-time snapshots of active weekly/monthly subscribers: daily for weekly plans, every 3 days for monthly;
- each carries `as_of_at` and `renewal_due_at`; the label is no renewal at the next renewal;
- unresolved renewals are censored;
- 109,599 snapshots from 3,863 subscribers; 11,717 censored.

**Holdout:** training uses renewals resolved before 5 Oct (61,528 snapshots); the untouched holdout covers 5–31 Oct
(28,020 snapshots, churn 10.1%).

| CatBoost model | Brier | PR-AUC | ROC-AUC | ECE | Lost revenue in top 10% |
|---|---|---|---|---|---|
| static (sign-up attributes) | 0.0911 | 0.118 | 0.552 | 0.034 | 14.2% |
| temporal_behaviour (+ tenure, renewals, days to renewal) | 0.0907 | 0.118 | 0.556 | 0.023 | 15.5% |
| **temporal (+ auto-renew status over time), deployed** | **0.0601** | **0.518** | **0.767** | **0.016** | **45.6%** |

- **Temporal vs static:** Brier gain **+0.031** (95% CI 0.028–0.034).
- **Risk evolves:** churners rise from 12.5% predicted risk 7 days before renewal to **74.8%** the day before;
  renewers fall to 5.3%.
- **Calibration:** the riskiest decile is accurate (0.439 predicted vs 0.436 observed). Overall the model predicts
  11.7% vs 10.1% actual, because churn drifted down.
- **Engineering:**
  - an overfitting grid was caught and replaced by a regularized one (chosen by chronological CV only);
  - training stays outside the services; the artifact is CatBoost `.cbm` with a SHA-256 checksum, no pickle.

### 4.3 Feature experiments: nothing else passed

Rule for every candidate: lower Brier in **all** chronological folds **and** a holdout 95% CI above zero.

| Candidates | Result |
|---|---|
| Onboarding/first-day attributes | **help a little** (+0.0004 to +0.0010 Brier, CIs > 0); in all models |
| Auto-renew toggles, plan changes, first renewal after offer, price vs country median, prior refunds | no: constant or duplicates in this data |
| Switch-off timing, `ab_test`, first offer, locale, install time, days to first purchase, cohort churn rates (channel/country/paywall) | no |
| Cumulative net revenue, revenue per subscribed day (point-in-time; replaces Adapty's leaky `total_revenue_usd`) | no |
| Recalibration (Platt, fitted on the 21 days before the holdout) | **not deployed**: rate 11.7% → 11.2%, but Brier/ECE worse; churn kept drifting (window 12.1%, holdout 10.1%) |

`cancellation_reason` is never used (it's only known after a subscription ends); a test enforces this.

### 4.4 Where the model is weak: auto-renew still ON

Real evaluation of the deployed model on 27,024 holdout snapshots where auto-renew is still on:

| Days before renewal | Snapshots | Churn | ROC-AUC (95% CI) | PR-AUC (95% CI) | Lost revenue in top 10% (95% CI) |
|---|---|---|---|---|---|
| 30+ | 0 | — | — (empty by construction: censored) | — | — |
| 15–30 | 932 | 6.1% | 0.550 (0.450–0.655) | 0.077 (0.045–0.135) | 19.2% (5.9%–35.2%) |
| 7–14 | 4,123 | 9.5% | 0.597 (0.566–0.628) | 0.120 (0.105–0.139) | 14.4% (11.1%–18.1%) |
| 1–6 | 21,969 | 6.3% | 0.640 (0.624–0.655) | 0.096 (0.086–0.108) | 20.0% (18.0%–22.0%) |

The model mostly **detects** decisions already made. Before a user cancels, ranking is modest, and at 15–30 days it's no
better than random. This data has nothing that could warn earlier.

### 4.5 Serving, storage, dashboard

- **Contract:** optional `as_of_at`, `renewal_due_at`, `renewal_price_usd`; old payloads stay valid.
- **Postgres:** new columns; views `churn_risk_trajectory` (with the change since the previous prediction and revenue at
  risk) and `churn_risk_current`; analytics endpoint `GET /v1/metrics/churn-trajectory`.
- **Grafana: "Churn Risk Over Time":**
  - current probability;
  - revenue at risk;
  - risk trajectory;
  - change since previous;
  - mean risk over time;
  - largest increases.
- **Replay:** `scripts/score_temporal_snapshots.py` replays snapshots through `/v1/predict` (1,750 requests validated
  offline).

---

## 5. Usage-data support (`docs/USAGE_FEATURES.md`)

- **Table and loader:**
  - `usage_events` table with idempotent loads;
  - loader for Amplitude, Firebase and CSV exports;
  - matching on `customer_user_id` with a match report.
- **Point-in-time features:** sessions in 7/30 days, days since last session, 7-day trend; only events **strictly
  before** `as_of_at`; untracked users get nulls. Proven by 12 tests on a hand-made fixture.
- **SIMULATED pipeline check (not a result):**
  - random synthetic usage adds nothing;
  - an injected "sessions fade before churn" signal is detected only where it exists (1–14 days before renewal), not
    at 15–30 days.

  This shows the pipeline works and doesn't leak; it says nothing about real gains.
- **Not used** by the deployed model. Real exports must pass the same ablation rule first.

---

## 6. The live Adapty account

| App | Contents | Verified |
|---|---|---|
| **Lumen - AI Photo Editor (Hackathon)** `cc1f40d1-…` | catalog (6 products, 7 flows, 5 placements, segments, 4 demo A/B tests); 6,000 profiles, 3,123 transactions | 24/24 field-by-field checks vs the offline data |
| **Lumen 50k** `92ceed1c-…` | 50,000 profiles, 29,794 transactions (no same-day purchases, so no tracked revenue) | 22 passed, 2 skipped (by design) |

- **What the profile API returns:** only current state, with the latest receipt.
- **Adapty-specific representations** (the tests encode them):
  - refunds set the expiry to the purchase time and revenue to $0;
  - lifetime purchases appear as subscriptions without expiry;
  - the offer shown is the latest receipt's;
  - non-USD revenue uses Adapty's exchange rates.
- **Simulated discount A/B test on `main`:**
  - 3 products at 30% off, a discounted paywall, 150 simulated users, 25 purchases;
  - the result is noise (−0.5 points, p = 0.94); it proves the pipeline, not a discount;
  - the original test is *completed*; a live copy *(test, copy)* is running.
- **Incident, fully restored:** an interrupted cleanup stopped the original test and deleted 23 simulated profiles; all
  23 were re-created.
- **Rules now in place:** no destructive Adapty calls and nothing that adds tracked revenue without asking.
- **Billing:** only simulated purchases count toward tracked revenue: about **$582 + $34**, far under the $5,000/month
  free tier. No real money moved.
- **Field inventory:** most event-level fields (prices, discounts, paywall, variation, attribution) **aren't** in the
  profile API; they need a webhook or Event Feed export.

---

## 7. Repository, branches, tests

**Branches (GitHub `DMustache/adapty-hack`):**

| Branch | State |
|---|---|
| `main` | everything above, including this summary |
| `temporal-churn` | contained in `main` (2 commits behind; redundant) |
| `model-implementation` | contained in `main` (redundant) |

`main` was updated directly, bypassing the team's Lead-review rule, at the user's request.

**Tests (all passing at the last runs):**

| Suite | Result |
|---|---|
| Team suite (`python -m pytest`) | 93 passed |
| Discount Advisor core (`cd discount_advisor; python -m pytest tests --ignore tests/test_app.py`) | 148 passed, 24 skipped |
| Discount Advisor app (`tests/test_app.py`) | 40 passed |
| Live Adapty checks (`ADAPTY_LIVE=1`) | 24 passed (5k app), 22 passed + 2 skipped (50k app) |

**Running things:**

| What | Command |
|---|---|
| Discount Advisor | `cd discount_advisor && streamlit run app.py` (set `DISCOUNT_DATA_DIR` to the offline data folder) |
| Services + Grafana | `docker compose up --build -d` (fresh volume, or apply `postgres/init/003-…` and `004-…` by hand), then `python scripts/score_temporal_snapshots.py --data-dir …` |
| Retrain / re-evaluate the churn model | `python -m ml.temporal_churn.train`, then `ablation`, `ablation_history`, `ablation_round2`, `ablation_revenue`, `recalibrate`, `eval_on_by_horizon` |
| Usage data | `python -m ml.usage.loader EXPORT … [--database-url URL]` |

The offline data is not in the repo: point `DISCOUNT_DATA_DIR` / `LUMEN_DATA_DIR` at the hackathon clone's
`data/offline`.

---

## 8. Limitations

- **Synthetic data:** nothing has been validated on real users.
- **Discount response is assumed, not measured.** No real discount test has been run.
- **Churn signal before cancellation is weak.** There's no usage data; ROC-AUC 0.55–0.64 for auto-renew-ON users.
- **The churn-rate level runs ~1.6 points high** because of drift. Recalibration needs ongoing monitoring.
- **Annual renewals are unobservable.** Long horizons are partly extrapolated.
- **Revenue, not profit.** Costs are only an optional assumption in the Discount Advisor.
- **The end-to-end Docker / Grafana run hasn't been performed** (no Docker on the development PC).

## 9. Open items and next steps

**Open now:**
1. Rotate the Lumen app's secret key: it was pasted in chat (App settings → General).
2. Run the services end to end with Docker and check the "Churn Risk Over Time" dashboard.
3. Tell the team that `main` changed without Lead review. Contract fields were added (optional, backward compatible).
4. Decide on the live simulated discount test copy. It's free to leave running; stopping is your call.
5. Optionally delete the redundant `temporal-churn` / `model-implementation` branches on GitHub.

**Next steps for a real product:**
1. Run a **real** paywall-structure test, then a discount test on the winner, with real users (affects billing; needs
   approval).
2. Load **real usage data** (Amplitude/Firebase) and run it through the ablation rule before deploying.
3. Monitor predicted vs actual churn rates and refit the calibration on a rolling window.
4. Add costs to move from revenue to profit.
