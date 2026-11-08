# Smart Retention Offers: complete reference

*Adapty hackathon · Lumen (AI photo editor, synthetic data) · written 2026-11-08*

This is the single document with **everything**: the data, every formula, how each model works and was evaluated,
the full pipeline from raw events to experiments, the code map, how to run and test it, the repository state, the
limitations and what comes next. Every number comes from a generated report or test run; where a number is
**SIMULATED**, it says so.

**Labels used throughout**

| Label | Meaning |
|---|---|
| **DATA** | measured from the dataset |
| **CALCULATED** | exact arithmetic on measured data |
| **ASSUMED** | an input you choose; not measured |
| **SIMULATED** | produced from synthetic activity to check the pipeline; never a result |

---

## Contents

1. [The big picture](#1-the-big-picture)
2. [The data](#2-the-data)
3. [Discount Advisor: acquisition discounts](#3-discount-advisor-acquisition-discounts)
4. [Temporal churn model (CatBoost)](#4-temporal-churn-model-catboost)
5. [Usage (Firebase / Amplitude) features](#5-usage-firebase--amplitude-features)
6. [Retention offers: churn risk → renewal-discount experiments](#6-retention-offers-churn-risk--renewal-discount-experiments)
7. [The full pipeline, end to end](#7-the-full-pipeline-end-to-end)
8. [Services, contracts, storage, dashboards](#8-services-contracts-storage-dashboards)
9. [The live Adapty account](#9-the-live-adapty-account)
10. [Code map](#10-code-map)
11. [How to run everything](#11-how-to-run-everything)
12. [Tests](#12-tests)
13. [Repository and branch state](#13-repository-and-branch-state)
14. [Limitations](#14-limitations)
15. [Open items and next steps](#15-open-items-and-next-steps)
16. [Glossary](#16-glossary)

---

## 1. The big picture

The project answers two questions for a subscription app:

1. **Acquisition:** is a discount on the paywall worth testing, and which one? → **Discount Advisor**
2. **Retention:** which existing subscribers are about to churn, how much revenue is at risk, and what renewal
   discount could be tested on them? → **temporal churn model** + **Retention offers**

Both follow the same principle: **we never claim a discount works.** The data contains no discount exposure, so price
response can't be measured. The tools compute exactly what a discount would *have to* achieve (break-even), and
design a randomized test that can find out.

```text
                 ┌─────────────────────── ACQUISITION ───────────────────────┐
installs, receipts ─► Discount Advisor ─► break-even lift ─► scenarios ─► "test X% off" or "keep full price"
                 └────────────────────────────────────────────────────────────┘

                 ┌──────────────────────── RETENTION ─────────────────────────┐
receipts (+ usage) ─► point-in-time snapshots ─► CatBoost churn risk ─► PostgreSQL ─► at-risk list
                    ─► revenue at risk ─► break-even renewal discount ─► randomized experiment plan
                 └────────────────────────────────────────────────────────────┘
```

---

## 2. The data

The Adapty hackathon *Lumen* app is **synthetic**.

| | |
|---|---|
| Installs | 50,000 (5 Jul – 2 Nov 2026) |
| Receipts | 29,794 |
| Paying users | 9,722 |
| Observation cutoff | **3 Nov 2026 00:07 UTC**: the last *observed* event. Scheduled `expires_at` dates (up to Nov 2027) are never used as a cutoff |

**Contained:**
- one price per product per country;
- trials, renewals, cancellations (auto-renew switch-offs), refunds, billing issues;
- the paywall placement and flow each user saw;
- three randomized A/B tests;
- first-day attributes: `ai_edits_first_day`, `photos_imported`, onboarding goal, push opt-in.

**Missing:**
- any discount exposure or within-market price variation, so price sensitivity can't be learned;
- any usage or engagement history (sessions, app opens);
- annual renewals (only ~17 weeks of history);
- costs.

**Data semantics** (each checked by a test):
- one payment chain per user, contiguous receipts, no re-subscriptions;
- trials are $0 receipt #0;
- refunds hit only the last receipt;
- the first paid receipt comes ≤ 9 days after install, so conversion uses a **14-day window**.

**Confounding trap:** cheaper countries convert *less* (India at 35% of the US price: 8.3% conversion; US: 26.6%).
Country drives both price and willingness to pay, so comparing countries says nothing about how users respond to a
discount.

**The three randomized A/B tests in the data** (balanced arms, so these are causal effects):

| Test | Conversion | Revenue per install |
|---|---|---|
| Onboarding: annual trial → **weekly first** | 11.3% → 22.3% (+96%) | +106% |
| Settings: upgrade → **lifetime anchor** | 17.5% → 25.0% (+43%) | +51% |
| Main (US/CA): 3 plans → **lifetime anchor** | 23.9% → 30.2% (+26%) | +37% |

At full price, changing the paywall structure raised conversion by 26–96%. Hence the main business recommendation:
**test paywall structure first, then discounts on the winning paywall.**

---

## 3. Discount Advisor: acquisition discounts

A Streamlit app (`discount_advisor/`). It recommends an **experiment**, never a "proven best discount". It works in
three steps: **calculate** what each discount must achieve (exact), **assume** how customers might react (your
input, with a range), **pick** the discount worth testing or say "keep full price".

### 3.1 Inputs (per audience)

| Symbol | Meaning | Source |
|---|---|---|
| c₀ | baseline conversion: share of installs paying within 14 days | DATA |
| V₀ | expected revenue per payer over the horizon (after refunds) | DATA (renewal curves) |
| a | share of that revenue the discount touches | DATA (plan mix × renewal curves) |
| d | discount, e.g. 0.35 = 35% off | you choose |
| k | step-up churn: extra cancellations when full price returns | ASSUMED, default 0.3 |
| ρ | value of a discount-driven buyer relative to a regular one | ASSUMED, default 0.85 |
| q | market ceiling: conversion can never exceed q × c₀ | ASSUMED, default 2 |
| fee | store fee | default 0.15 |
| g | variable cost per paid period, share of list price | ASSUMED, default 0 |

### 3.2 Value of a payer after the discount (share of V₀)

```
v_d = (1 − d) · a  +  (1 − a) · (1 − k · d)
```

- `(1 − d) · a`: the payments during the discount, at the lower price.
- `(1 − a) · (1 − k · d)`: the later full-price payments, minus the extra cancellations when the price steps up.

### 3.3 Break-even lift

The relative increase in conversion a discount needs just to break even:

```
L* = (1 / v_d − 1) / ρ          conversion needed = c₀ · (1 + L*)
```

**Worked example**, onboarding, 35% off the first payment (a = 0.49, k = 0.3, ρ = 0.85, c₀ = 16.8%):

```
v_d = 0.65 × 0.49 + 0.51 × (1 − 0.3 × 0.35) = 0.3185 + 0.4565 = 0.775
L*  = (1 / 0.775 − 1) / 0.85 = 0.290 / 0.85 = 34.2%
conversion needed = 16.8% × 1.342 ≈ 22.5%
```

### 3.4 With costs (optional)

```
payments kept   P_d = a + (1 − a) · (1 − k · d)
margin          m_d = (1 − fee) · v_d − g · P_d
break-even      L*  = (m₀ / m_d − 1) / ρ
```

A discount cuts the price but not the cost, so break-even rises. If m_d ≤ 0, no increase in conversion can ever pay
for the discount. With g = 0, the fee cancels and you get the simple formula.

### 3.5 Assumed customer response: the conversion curve

You state one thing: **how much a 20% discount would lift conversion**, as low / most likely / high
(default 5% / 20% / 50%). This becomes a curve c(d):

```
m      = min(1, q · c₀)                                    market ceiling
c(d)   = m · Φ̄( Φ⁻¹(1 − c₀/m) + ln(1 − d) / σ )            Φ = standard normal CDF, Φ̄ = 1 − Φ
σ      chosen so that c(0.20) = c₀ · (1 + stated 20% lift)
```

Properties: c(0) = c₀ exactly (pinned to today's measured conversion); diminishing returns (each extra 5% of discount
brings fewer buyers); never above the ceiling m. The tool draws **4,000 scenarios** from a triangular distribution
over your low / likely / high answer, and also samples c₀ and V₀ from their measurement uncertainty.

### 3.6 Revenue per user shown the offer

```
R(d) = V₀ · [ c₀ · v_d  +  (c(d) − c₀) · ρ · v_d ]
```

- `c₀ · v_d`: existing buyers, now paying less (cannibalisation).
- `(c(d) − c₀) · ρ · v_d`: new buyers brought in by the discount.

The store fee multiplies everything equally; with costs, `v_d` becomes `m_d`.

### 3.7 Test size

Users per arm, two-sided two-proportion z-test (α = 0.05, power 0.8), detecting exactly the break-even change
p₁ = c₀ → p₂ = c₀ · (1 + L*):

```
n = [ z₁₋α/2 · √(2·p̄·(1 − p̄))  +  z₁₋β · √(p₁(1 − p₁) + p₂(1 − p₂)) ]²  /  (p₂ − p₁)²      p̄ = (p₁ + p₂)/2
```

With several discount arms, α is Bonferroni-split across comparisons. Weeks needed = 2n ÷ weekly eligible traffic.

### 3.8 Picking the discount

For each discount from 5% up to the maximum allowed (default 40%):
1. **Plausible?** It beats full price in ≥ 50% of the 4,000 scenarios.
2. **Testable?** A 50/50 test can detect its break-even lift within **8 weeks** at this audience's traffic.

Among discounts passing both, pick the highest expected revenue. If none passes: **"Keep full price; don't spend
traffic on a discount test yet."**

### 3.9 Results (default settings, 12-month horizon, discount on the first paid payment)

| Audience | Recommendation |
|---|---|
| onboarding, winning weekly-first paywall (`onb_weekly`) | **test 40% off**: break-even 36.7%, 456 users/arm, ≈ 3 weeks |
| onboarding, both paywalls (blend; the app warns) | test 35% off: break-even 34.2%, 751 users/arm, ≈ 3 weeks |
| onboarding, `onb_trial` only | test 25% off: break-even 26.9%, ≈ 7 weeks |
| main | **test 30% off**: break-even 30.9%, 753 users/arm, ≈ 4 weeks |
| ai_limit_reached, settings_upgrade | keep full price (annual plans: the discount hits all revenue) |
| win_back | keep full price (116 installs/week: no test fits in 8 weeks; 52% of value extrapolated) |

**Blended-audience warning:** the onboarding placement holds both arms of a randomized test, which convert very
differently (11.3% vs 22.3%). The app warns when an audience mixes paywalls.

**Tabs:** Recommendation · Sensitivity · Compare segments · Randomized tests · Baselines · Data reality check ·
Live Adapty · Method · Retention offers.

---

## 4. Temporal churn model (CatBoost)

### 4.1 What it predicts

**Failure to renew at the next eligible renewal event** (any reason: voluntary cancellation, billing failure, refund)
for an active weekly or monthly paid subscriber, observed at a point in time. Because it scores the same subscriber
repeatedly, you can follow how their risk **evolves** as the renewal approaches.

### 4.2 Snapshots (the training rows)

| | |
|---|---|
| Unit | one active weekly/monthly **paid** subscriber at an instant `as_of_at` inside a paid period |
| Cadence | daily for weekly plans, every 3 days for monthly plans, from the payment until the renewal is due |
| `renewal_due_at` | end of the current paid period = the next renewal event |
| Label | `churn = 1` if that renewal does not happen, else 0 |
| Censoring | labelled only if the renewal was resolved ≥ 1 day before the cutoff; later snapshots are scored but never trained or evaluated on |
| Counts | 109,599 snapshots from 3,863 subscribers; 11,717 censored |
| Leakage guard | every feature uses only events with timestamp ≤ `as_of_at`; a test rewrites all later events and checks earlier snapshots don't change |

### 4.3 The 23 features of the deployed model

| Group | Features |
|---|---|
| Static categorical (9) | `plan`, `platform`, `country`, `acquisition_channel`, `onboarding_goal`, `push_opt_in`, `app_version`, `placement`, `flow` |
| Static numeric (4) | `renewal_price_usd`, `price_index` (country annual-price median ÷ $49.99), `ai_edits_first_day`, `photos_imported` |
| Static boolean (1) | `started_with_trial` |
| Temporal numeric (7) | `tenure_days`, `renewal_count`, `days_until_renewal`, `days_since_last_payment`, `historical_renewal_success_rate`, `billing_issues_last_30d`, `days_since_install` |
| Status (2) | `auto_renew_off` (switched off at or before as_of_at), `days_since_auto_renew_off` |

Definitions (all at `as_of_at`):

```
tenure_days              = (as_of_at − first paid receipt) / 1 day
renewal_count            = renewals already happened = position in chain − 1
days_until_renewal       = (renewal_due_at − as_of_at) / 1 day
days_since_last_payment  = (as_of_at − last payment) / 1 day
historical_renewal_success_rate = 1.0 after ≥ 1 renewal, null before (a chain ends at its first failure)
billing_issues_last_30d  = billing issues detected in (as_of_at − 30 d, as_of_at]
auto_renew_off           = renew-status change to OFF dated ≤ as_of_at
days_since_auto_renew_off= (as_of_at − that change) / 1 day, null if still on
```

Data limits: in this synthetic data `historical_renewal_success_rate` is always 1.0 or null, and
`billing_issues_last_30d` is always 0 at snapshot time (billing issues are only recorded at the final failed renewal).
They are kept because they would carry signal on real data. `cancellation_reason` is **never** used: it is only known
after a subscription ends (a test enforces this).

### 4.4 How the model is trained

- **Algorithm:** CatBoost gradient-boosted trees (native categorical handling, missing values allowed), seed 7.
- **Temporal holdout:** test = labelled snapshots in the last 28 days before the last resolvable renewal
  (5–31 Oct, 28,020 snapshots, 2,130 subscribers, churn 10.1%). Train = snapshots whose renewal was resolved
  **before** the test window starts (61,528 snapshots, 2,412 subscribers). No training outcome overlaps the test.
- **Hyperparameters:** chosen only by **chronological forward-chaining CV** inside the training period (3 folds,
  purged the same way), minimizing log loss. Grid: depth ∈ {3, 4, 6} × iterations ∈ {100, 300}, learning rate 0.03,
  L2 10. The first grid (500 rounds) overfit badly and was replaced. Every model chose depth 3, 100 rounds.
- **Artifact:** CatBoost `.cbm` (no pickle) + SHA-256 + `metadata.json` (feature order, JSON input schema, metrics,
  provenance). The service refuses to load on a checksum mismatch.

### 4.5 Metrics used

```
Brier       = mean (p − y)²                         lower = better; compared with a constant at the test churn rate
Log loss    = −mean [ y·ln p + (1 − y)·ln(1 − p) ]
PR-AUC      = area under precision–recall (average precision)
ROC-AUC     = probability a random churner is ranked above a random renewer
ECE         = Σ_bins (n_bin/N) · |mean(y) − mean(p)|      10 equal-count bins
Calibration slope/intercept = logistic regression of y on logit(p)  (ideal 1 / 0)
Lost revenue in top k%      = Σ(y · price) of the top k% by p·price  ÷  Σ(y · price)
Brier gain (A vs B)         = Brier(A) − Brier(B), 95% CI from a subscriber-clustered bootstrap (500 draws)
```

### 4.6 Results (untouched holdout)

| CatBoost model | Brier (constant) | PR-AUC | ROC-AUC | ECE | Lost revenue top 10% / 20% |
|---|---|---|---|---|---|
| static (sign-up attributes) | 0.0911 (0.0905) | 0.118 | 0.552 | 0.034 | 14.2% / 27.7% |
| temporal_behaviour (+ tenure, renewals, timing) | 0.0907 (0.0905) | 0.118 | 0.556 | 0.023 | 15.5% / 27.9% |
| **temporal (+ auto-renew status) — deployed v1.0.0** | **0.0601** (0.0905) | **0.518** | **0.767** | **0.016** | **45.6% / 56.7%** |

Brier gain, temporal vs static: **+0.0310 (95% CI +0.0279 to +0.0340)**.

**Risk evolves** (mean predicted risk on the holdout):

| Days until renewal | 7 | 6 | 5 | 4 | 3 | 2 | 1 |
|---|---|---|---|---|---|---|---|
| Renewed | 0.124 | 0.106 | 0.107 | 0.093 | 0.071 | 0.061 | 0.053 |
| Churned | 0.125 | 0.216 | 0.257 | 0.393 | 0.532 | 0.611 | **0.748** |

PR-AUC rises from 0.20 at 5–8 days out to **0.80** in the last day.

**Calibration:** the top risk decile is accurate (0.439 predicted vs 0.436 observed). Overall the model predicts
11.7% vs 10.1% actual because churn drifted down from ~11% in training.

**Recalibration** (Platt, fitted on the 21 days before the holdout with out-of-time predictions): moved the level to
11.2% but made Brier (0.0604) and ECE (0.0167) worse. **Not deployed.** The right production tool is monitoring
predicted vs realized rates and refitting on a rolling window.

### 4.7 What the model really learns

The time-aware gain comes almost entirely from **auto-renew status over time**: seeing that a subscriber switched it
off, and since when. Before a user cancels, ranking is modest:

| Auto-renew still ON, days before renewal | Snapshots | Churn | ROC-AUC (95% CI) | PR-AUC | Lost revenue top 10% |
|---|---|---|---|---|---|
| 15–30 | 932 | 6.1% | 0.550 (0.450–0.655) | 0.077 | 19.2% |
| 7–14 | 4,123 | 9.5% | 0.597 (0.566–0.628) | 0.120 | 14.4% |
| 1–6 | 21,969 | 6.3% | 0.640 (0.624–0.655) | 0.096 | 20.0% |

So the model mostly **detects decisions already made**, early enough before the renewal to act. At 15–30 days it is
no better than random: this data has nothing that warns earlier. That gap is what usage data (section 5) is for.

### 4.8 Feature experiments (all evaluated, only one kept)

**Acceptance rule**, fixed before running: lower Brier in **every** chronological CV fold **and** a holdout 95% CI of
the Brier gain above zero.

| Candidates | Result |
|---|---|
| Onboarding / first-day attributes | **kept**: +0.0004 to +0.0010 Brier, CIs > 0 |
| Auto-renew toggles, plan changes, first renewal after offer, price vs country median, prior refunds | no: constant or duplicates in this data |
| Switch-off timing, `ab_test`, first offer, locale, install time, days to first purchase, cohort churn rates | no |
| Cumulative net revenue, revenue per subscribed day (point-in-time) | no |
| Recalibration | not deployed (see 4.6) |

---

## 5. Usage (Firebase / Amplitude) features

**New in this version.** A complete pipeline that consumes real Firebase / Amplitude exports when they exist, keeping
the deployed 23-feature model **unchanged** as the baseline.

### 5.1 Loading

- **Formats** (plain or gzipped):
  - Amplitude Export API JSON lines: `user_id`, `event_type`, `event_time`
  - Firebase → BigQuery JSON lines: `user_id`, `event_name`, `event_timestamp` (microseconds since epoch)
  - CSV: `user_id, event_name, occurred_at` (naive times read as UTC)
- Rows without a user, event name or time are dropped and counted; duplicates (user, event, time, source) removed.
- **Matching:** the export's `user_id` must equal Adapty's `customer_user_id`. Subscribers come from local files
  (offline users + seeding run id: offline `u00042` = `lumen_<run>_00042`; or a cached profiles file). A match report
  lists matched / unmatched users and events.
- **Storage (optional):** `usage_events` table (`postgres/init/007-usage-events.sql`), unique on (user, event, time,
  source) so reloading is idempotent, indexed by (user, time). `read_events()` reads it back.

### 5.2 Point-in-time engagement features

Only events **strictly before** `as_of_at` count. A session = an event named `session_start`, `app_open` or
`[Amplitude] Start Session`. For a snapshot at time t, with S(a, b) = number of sessions in [a, b):

```
sessions_7d              = S(t − 7d,  t)
sessions_14d             = S(t − 14d, t)
sessions_30d             = S(t − 30d, t)
days_since_last_session  = t − last session before t            (null if none yet)
days_since_last_activity = t − last event of ANY kind before t
sessions_trend_7d_delta  = S(t − 7d, t) − S(t − 14d, t − 7d)
sessions_trend_7d_ratio  = (S(t − 7d, t) + 1) / (S(t − 14d, t − 7d) + 1)
session_rate_7d_vs_30d   = (sessions_7d + 1) / (sessions_30d · 7/30 + 1)    < 1 = usage fading
```

**Missing history is explicit.** A subscriber with no usage history gets **nulls, not zeros**, so "not tracked" never
looks like "inactive". Whether a subscriber is tracked is itself decided point-in-time (at least one event before t),
because deciding it from all their events would leak the future. If the tracking start is known (e.g. SDK rollout),
`tracked_since` makes tracked-but-inactive subscribers get zero sessions instead.

### 5.3 Training: baseline vs usage model

`python -m ml.temporal_churn.train_usage --usage EXPORT… [--export]` (or `--database-url URL`):

| Model | Features | Role |
|---|---|---|
| `temporal` | the deployed 23 | baseline, unchanged; its artifact is never written |
| `temporal_usage` | the same 23 + 8 usage features | candidate |

Same snapshots, labels, 28-day temporal holdout, chronological CV grid and seed as the deployed model. The same
**acceptance rule** decides: better Brier in every fold **and** holdout CI above zero. The report adds usage coverage
and Brier separately for snapshots with and without usage history.

`--export` writes `services/inference/models/temporal_usage_catboost/` with `model_id` `lumen-temporal-usage-catboost`
0.1.0; its metadata records the baseline's id, version and checksum, the verdict, and that usage features are
optional. **Simulated guard:** with synthetic events every output is labelled SIMULATED and the model can only be
exported to an explicit folder, never the service's.

### 5.4 Inference

- Served as an **optional second model** next to the deployed one; loaded only if its artifact is installed.
  Callers opt in with its `model_id`. Analytics, Retention offers and the scoring script keep using the deployed
  model by default.
- The adapter refuses an artifact whose checksum doesn't match, whose first 23 features differ from the deployed
  model's (names or order), or whose usage features aren't optional and nullable.
- Request schema: the 23 baseline features are required; usage features may be omitted or null (same prediction
  either way, matching training). Unknown features are rejected; the same UTC time checks apply.
- Scoring: `scripts/score_temporal_snapshots.py --model-id lumen-temporal-usage-catboost --usage EXPORT…`.

### 5.5 SIMULATED pipeline check

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

---

## 6. Retention offers: churn risk → renewal-discount experiments

Connects the churn model to discounts for **existing subscribers before their next renewal**.

### 6.1 Latest valid prediction per subscriber (`GET /v1/retention/at-risk`)

- From `lumen-temporal-catboost`, with churn probability, renewal price, renewal date and plan.
- Reference time: a chosen date, or the newest prediction in the database.
- Per subscriber, the newest prediction at or before the reference time. It is **dropped, never replaced by an older
  one**, if its renewal is already due or it is older than 7 days. Exclusions are counted. All times UTC.

### 6.2 Formulas

With churn probability p, renewal price P, discount d, renewal probability p₀ = 1 − p:

```
revenue at risk              = p · P                         (rounded to cents, half-up)
renewal needed to break even = p₀ / (1 − d)                  relative increase  = d / (1 − d)
                                                              10% → +11%, 20% → +25%, 30% → +43%
can break even at all        ⇔ p₀ / (1 − d) ≤ 1  ⇔  p ≥ d   (only subscribers at least as risky as the discount)
discount cost on renewers    = Σ (1 − p) · P · d             (what the extra renewals must win back)
users per arm                = two-proportion test at exactly the break-even change (section 3.7),
                               α = 0.05 Bonferroni-split across discount arms, power 0.8
```

Why `p₀ / (1 − d)`: at full price expected revenue is p₀ · P; with the discount it is p₁ · (1 − d) · P. Equal when
p₁ = p₀ / (1 − d).

### 6.3 The experiment

The planner (`make_plan`, also `POST /v1/retention/plan`) randomizes eligible subscribers into a **control** arm and
rotating discount arms, caps the face-value discount exposure by a budget in whole cents, and stores the plan
immutably in PostgreSQL. The Streamlit preview uses the same code and fingerprint as the API.

### 6.4 The tab

| Section | Shows |
|---|---|
| Subscribers at risk | table with filters (risk, days to renewal, plan) |
| Revenue exposure | totals by risk band, days until renewal, plan |
| Discount scenarios | per discount: who can break even, renewal needed, cost on renewers, users per arm |
| Experiment recommendation | testable now or renewal cohorts needed; arm preview; register button |

**Honesty rule:** there is no observed discount-response data, so the tab shows break-even thresholds and a test
design only. It never names an optimal discount or promises revenue (tests enforce the wording).

---

## 7. The full pipeline, end to end

```text
 RAW DATA                         FEATURES                       MODELS                      DECISIONS
 ────────                         ────────                       ──────                      ─────────
 users.csv.gz ─┐
 transactions ─┼─► periods() ─► build_snapshots() ──────┐
               │   (paid weekly/monthly periods)         │   23 features, label, censoring
               │                                          ├─► train.py ─► temporal_catboost 1.0.0 (deployed)
 Amplitude ────┤                                          │
 Firebase  ────┼─► loader ─► match ─► usage_features() ──┴─► train_usage.py ─► temporal_usage_catboost
 CSV       ────┘   (usage_events)    (strictly < as_of_at)     baseline vs candidate, acceptance rule

 SERVING
 ───────
 score_temporal_snapshots.py ─► POST /v1/predict (inference) ─► adapter (checksum, schema) ─► probability
                                         │
                                         └─► analytics POST /v1/ingest/predictions ─► churn_predictions (PostgreSQL)
                                                                                         │
            Grafana "Churn Risk Over Time" ◄── views churn_risk_trajectory / churn_risk_current
                                                                                         │
            Retention offers tab ◄── GET /v1/retention/at-risk ◄────────────────────────┘
                     │ revenue at risk, break-even scenarios, sample size
                     └─► POST /v1/retention/plan ─► retention_experiments (immutable)

 ACQUISITION
 ───────────
 users + receipts ─► measured c₀, V₀, a ─► v_d, L* ─► 4,000 scenarios ─► plausible? testable? ─► recommendation
```

---

## 8. Services, contracts, storage, dashboards

- **Inference** (FastAPI, port 8001): `/v1/models`, `/v1/models/{id}/schema`, `/v1/predict`,
  `/v1/retention/plan`, `/v1/retention/draft/check`. Adapters: mock, `lumen-temporal-catboost`, and (if installed)
  `lumen-temporal-usage-catboost`.
- **Analytics** (FastAPI, port 8002): ingest predictions / experiments / lineage / actuals;
  `/v1/metrics/churn-risk`, `/v1/metrics/churn-trajectory`, `/v1/retention/at-risk`.
- **Contract additions** (all optional, backward compatible): `as_of_at`, `renewal_due_at`, `renewal_price_usd`,
  `plan_type` on churn predictions.
- **PostgreSQL:** `churn_predictions` (+ temporal columns, `plan_type`), views `churn_risk_trajectory` (with change
  since the previous prediction and revenue at risk) and `churn_risk_current`, `retention_experiments`,
  `usage_events`.
- **Grafana "Churn Risk Over Time":** current probability, revenue at risk, risk trajectory, change since previous,
  mean risk over time, largest increases.

---

## 9. The live Adapty account

| App | Contents | Verified |
|---|---|---|
| Lumen - AI Photo Editor (Hackathon) | catalog (6 products, 7 flows, 5 placements, segments, 4 demo A/B tests); 6,000 profiles, 3,123 transactions | 24/24 field checks vs offline data |
| Lumen 50k | 50,000 profiles, 29,794 transactions | 22 passed, 2 skipped by design |

- The profile API returns only current state with the latest receipt; most event-level fields need a webhook or
  Event Feed export.
- A simulated discount A/B test on `main` (30% off, 150 simulated users): result is noise (p = 0.94); it proves the
  pipeline, not a discount. A live copy is running.
- Tracked revenue from simulated purchases ≈ $582 + $34, far under the free tier. No real money moved.
- Rules: no destructive Adapty calls and nothing adding tracked revenue without asking.

---

## 10. Code map

| Path | What it does |
|---|---|
| `discount_advisor/economics.py` | `value_factor`, `margin_factor`, `break_even_lift`, `conversion_at`, `simulate`, `ab_sample_size`, `plan_test` |
| `discount_advisor/app.py`, `retention_tab.py`, `retention_offers.py` | Streamlit app, Retention offers tab and its calculations |
| `ml/temporal_churn/snapshots.py` | load data, observation cutoff, periods, snapshots, all point-in-time features, `add_usage_features`, `feature_record` |
| `ml/temporal_churn/train.py` | holdout, chronological CV, fit/predict, metrics, bootstrap, export of the deployed model |
| `ml/temporal_churn/train_usage.py` | baseline vs usage model, acceptance rule, report, usage-model export |
| `ml/temporal_churn/ablation*.py`, `recalibrate.py`, `eval_on_by_horizon.py` | feature experiments and evaluations |
| `ml/usage/loader.py` | Amplitude / Firebase / CSV parsing, matching, Postgres insert/read |
| `ml/usage/features.py` | point-in-time usage features |
| `ml/usage/simulated_check.py` | SIMULATED activity generator and end-to-end check |
| `services/inference/app/adapters/temporal_catboost.py` | deployed model adapter (pinned checksum, 23 features) |
| `services/inference/app/adapters/temporal_usage_catboost.py` | optional usage-model adapter |
| `services/inference/app/economics.py` | `break_even`, `make_plan` (retention planner) |
| `services/analytics/app/main.py` | storage and read APIs |
| `scripts/score_temporal_snapshots.py` | replay snapshots through `/v1/predict` |
| `postgres/init/*.sql` | schema, temporal predictions, experiment lineage, retention candidates, usage events |

---

## 11. How to run everything

The offline data isn't in the repo: set `LUMEN_DATA_DIR` / `DISCOUNT_DATA_DIR` to the hackathon clone's
`data/offline`.

| What | Command |
|---|---|
| Discount Advisor | `cd discount_advisor && streamlit run app.py` |
| Services + Grafana | `docker compose up --build -d` (fresh volume, or apply new `postgres/init/*.sql` by hand) |
| Score snapshots (deployed model) | `python scripts/score_temporal_snapshots.py --data-dir …` |
| Score with the usage model | `python scripts/score_temporal_snapshots.py --model-id lumen-temporal-usage-catboost --usage EXPORT…` |
| Retrain the deployed model | `python -m ml.temporal_churn.train` |
| Load usage exports | `python -m ml.usage.loader EXPORT… [--database-url URL]` |
| Train/evaluate the usage model | `python -m ml.temporal_churn.train_usage --usage EXPORT… [--export]` |
| SIMULATED pipeline check | `python -m ml.usage.simulated_check` |
| Tests | `python -m pytest -q` |

---

## 12. Tests

| Suite | Result |
|---|---|
| Team suite on the usage branch (`python -m pytest`) | **115 passed, 8 skipped** |
| of which `tests/test_usage.py` | 15 passed: formats, invalid rows, idempotent reload, match report, exact feature values, events at/after as_of ignored, point-in-time tracking, `tracked_since` |
| of which `tests/test_usage_pipeline.py` | 11 passed (SIMULATED data): feature set = deployed 23 + usage; null path; no future leakage at snapshot level; report labelled SIMULATED with no accuracy claim; simulated export blocked from the service folder; metadata; adapter with/without/null usage; tampered artifacts rejected; API serves both models side by side; scoring requests; deployed model checksum unchanged |
| Discount Advisor core / app / Retention tab (rescue branch) | 148 passed + 24 live skipped / 40 passed / 4 passed |
| Retention-offers integration tests on real PostgreSQL (rescue branch) | 11 passed |
| Live Adapty checks (`ADAPTY_LIVE=1`) | 24 passed (5k app); 22 passed + 2 skipped (50k app) |

---

## 13. Repository and branch state

GitHub `DMustache/adapty-hack`:

| Branch | Contents |
|---|---|
| `main` (team) | Lead-managed milestones M0–M7: services, pinned CatBoost 1.0.0, candidate API (`/v1/retention/at-risk`), `plan_type` propagation, Grafana dashboards. **Does not contain** the Discount Advisor, Retention offers tab or usage pipeline |
| `rescue/misplaced-main-2026-11-08` | our 11 commits that had been pushed straight to `main` (Discount Advisor, Retention offers, usage loader, docs). The team moved them here and integrated only the candidate API and billing-plan propagation |
| `usage-behavioral-features` (new) | built on the team's current `main`: the usage pipeline of section 5 |
| `temporal-churn`, `model-implementation` | older, redundant |

The team's workflow (`.workflow/README.md`): `main` belongs to the Lead; work goes through `task/<JOB-ID>` branches
into `develop`, passes a QA gate, then is promoted. Our new work is therefore pushed as a branch, not to `main`.

---

## 14. Limitations

- **Synthetic data:** nothing has been validated on real users.
- **Discount response is assumed, not measured.** No real discount test has been run.
- **Churn signal before cancellation is weak:** ROC-AUC 0.55–0.64 for auto-renew-ON users, no better than random
  at 15–30 days.
- **No real usage data yet:** the usage pipeline works on synthetic activity only; its value is unknown.
- **Churn level runs ~1.6 points high** because of drift; needs monitoring.
- **Annual renewals unobservable;** long horizons partly extrapolated.
- **Revenue, not profit,** unless you enter costs.
- **End-to-end Docker / Grafana run not performed on the development PC** (no Docker there); the team's gates ran it
  on their side for M0–M7.

---

## 15. Open items and next steps

**Open now**
1. Rotate the Lumen app's secret key (it was pasted in chat).
2. Agree with the Lead how the Discount Advisor, Retention offers tab and usage pipeline enter `develop` (job files,
   task branches), since `main` is Lead-only.
3. Decide on the running simulated discount test copy in Adapty.
4. Optionally delete the redundant `temporal-churn` / `model-implementation` branches.

**For a real product**
1. Run a real paywall-structure test, then a discount test on the winner (affects billing; needs approval).
2. Load real Amplitude / Firebase exports, run `train_usage`, deploy the usage model only if it passes.
3. Monitor predicted vs actual churn; refit calibration on a rolling window.
4. Add costs to move from revenue to profit.
5. Run the first renewal-discount test from the Retention offers tab on real subscribers (needs approval).

---

## 16. Glossary

| Term | Meaning |
|---|---|
| Snapshot | one subscriber observed at one instant `as_of_at`, with features known then |
| Censored | renewal not yet resolved at the data cutoff: scored, never trained or evaluated on |
| Break-even lift | the minimum improvement a discount needs to not lose money |
| Step-up churn (k) | extra cancellations when the discounted price returns to full price |
| Brier score | mean squared error of probabilities; lower is better |
| Chronological CV | validation folds always later in time than their training data |
| Clustered bootstrap | resampling whole subscribers (not rows) for honest confidence intervals |
| Acceptance rule | better Brier in every CV fold **and** holdout CI above zero |
| Point-in-time | uses only information available at the snapshot instant |
| SIMULATED | synthetic, a pipeline check only, never evidence of accuracy |
