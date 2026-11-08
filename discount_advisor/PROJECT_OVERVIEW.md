# Discount Advisor: Project Overview

*Adapty Hackathon · decision support for subscription discounts*

---

## 1. The question it answers

> **Should we test a discount for this subscription audience, and if so, which discount is worth testing?**

The tool recommends an **experiment to learn**, not a discount it has "discovered" to be best. The data is
**synthetic** and contains **no randomised discount exposure or discount variation**. Nothing in it can identify how
customers respond to a discount, so we don't train a discount-response model.

Every number in the app carries one of three labels:

| Label | Meaning | Example |
|---|---|---|
| **DATA** | computed directly from observed data | baseline conversion and its 95% CI |
| **CALCULATED** | exact arithmetic on measured inputs and stated assumptions | break-even lift, sample size, duration |
| **ASSUMED** | user-entered scenario values or model structure the data can't identify | lift from a 20% discount, market ceiling, response-curve shape |

---

## 2. The data, and what it means

Files: `users.csv.gz` (50,000 installs) and `transactions.csv.gz` (29,794 receipts) from the hackathon repo's
`data/offline/` folder. The data is **synthetic**: a fictional app called *Lumen*. The generator isn't included, so the tool
relies only on what is demonstrable in the files. Every rule below is asserted in `tests/test_data.py`.

| Topic | What the data shows | How the tool uses it |
|---|---|---|
| Keys | install = `user_id`; receipt = (`user_id`, `seq`) | |
| Placement | every install saw exactly one placement | the selected placement's installs are the audience |
| Payment chains | at most **one** chain per user (one `originally_purchased_at`); receipts contiguous, each starts when the previous expires; no re-subscriptions | unit of renewal analysis = chain |
| Trials | always `seq` 0, price $0, 3 days (weekly) or 7 days (annual trial) | a trial is **not** a paid receipt |
| Lifetime | one-time purchase, no expiry | a payer, but excluded from renewal metrics |
| Refunds | 612 receipts, always the user's last receipt | refunded receipt = $0 net; the user **remains a payer** |
| `expires_at` | runs up to Nov 2027 (scheduled, not observed) | never used as the cutoff |
| **Observation cutoff** | latest *observed event* (install, purchase, renewal-status change, billing issue, refund) = **2026-11-03 00:07:04 UTC** | outcomes after it are censored |
| Time to first paid receipt | at most 9.0 days observed; 6 days to first transaction + 7-day trial = 13 days theoretical max | **14-day conversion window** |

### What's missing
- **No discount, promo or intro-price offer** (`offer` is only `free_trial` or empty).
- **No price variation within a market** (one price per product × country), so price sensitivity is not identifiable.
- **~17 weeks of history**: annual renewals and long-run retention can't be observed.
- **No costs**: revenue, not profit.

### The confounding trap
Cheaper countries convert *less* (India at 35% of the US price converts far below the US). A naive model would
"learn" that higher prices increase conversion. Country drives both price tier and willingness or ability to pay, so the
regional chart in the **Data reality check** tab is explicitly *not* a discount-response estimate.

---

## 3. Measured baselines (DATA)

**Audience** = installs in the selected placement, optionally filtered by country, price tier, platform, acquisition
channel or flow.

**Conversion c₀** = share of *mature* installs (installed ≥ 14 days before the cutoff) whose first **paid** receipt
came within 14 days of install. Recent installs are excluded from the denominator rather than counted as non-payers.
Each c₀ comes with a **95% Wilson interval**.

**Renewal curves.** A discrete **Kaplan–Meier** estimate over paid receipts, one payment chain per payer.
- **Censoring rule:** a chain whose current paid period hadn't ended by the cutoff, and wasn't refunded, is
  censored. Its renewal is unknown. This includes users who switched auto-renew **off**. (An earlier version
  counted them as churned while treating auto-renewers as unknown. That biased renewal downwards; for example, monthly
  second-payment retention rises from 86.7% to **89.1%** after the fix.) A refund ends the entitlement on an observed
  date, so it counts as an event.
- A step counts as **observed** if at least 30 chains had a known outcome (weekly: 16 payments; monthly: 4).
  Beyond that, the **tail rule** repeats the mean of the last 3 observed renewal rates (weekly 92.5%, monthly 89.1%).
- Payments fall on days 0, P, 2P… (P = 7 / 30 / 365 days, as observed). The 3/6/12-month horizons count payments
  before day 91 / 182.5 / 365, so **annual plans always count as one payment**. The app warns that annual renewals and
  long horizons can't be measured.

**Revenue per payer V₀** = Σ over payers of (first paid price) × (1 − that plan's refund rate) × (expected
payments in horizon), averaged. It is reported **split** into first receipt / renewals estimated from data /
**extrapolated tail**, and shown next to the **observed net receipts per payer so far** (cash actually received).
V₀ is before store fee.

**Share touched by the discount, a.** Computed from the audience's own plan mix and renewal curves for the selected
horizon and discount scope: *first paid payment only*, *first month*, *first 3 months* or *every payment*.

### Placement baselines (12-month horizon, computed at runtime)
| Placement | Payers | c₀ (95% CI) | V₀ | Observed so far | Extrapolated | a (first payment) | Installs/week |
|---|---|---|---|---|---|---|---|
| onboarding | 4,108 | 16.8% (16.4–17.3%) | $48.83 | $37.81 | 12% | 49% | 1,597 |
| main | 2,299 | 19.5% (18.8–20.2%) | $64.51 | $44.14 | 24% | 56% | 771 |
| ai_limit_reached | 1,519 | 47.5% (45.8–49.3%) | $65.21 | $65.17 | 0% | 100% | 209 |
| settings_upgrade | 660 | 21.2% (19.8–22.7%) | $61.65 | $53.58 | 10% | 84% | 203 |
| win_back | 256 | 14.2% (12.7–15.9%) | $81.94 | $25.30 | **52%** | 14% | 116 |

The `win_back` value is mostly extrapolation, so treat any discount conclusion there with extra caution.

---

## 4. Discount economics (CALCULATED)

For discount *d*:

```
revenue kept   v_d = (1 − d) × a  +  (1 − a) × (1 − k × d)      (shares of V₀)
payments kept  P_d = a  +  (1 − a) × (1 − k × d)
margin         m_d = (1 − fee) × v_d  −  g × P_d
R(d)  = V₀ × ( c₀ × m_d  +  (c(d) − c₀) × ρ × m_d )   ← net contribution per eligible user
L*(d) = (m₀ / m_d − 1) / ρ                            ← break-even relative conversion lift
```

- `c₀ × m_d`: existing payers now pay less (**cannibalisation**).
- `(c(d) − c₀) × ρ × m_d`: new payers, worth ρ of an ordinary payer.
- `k`: **step-up churn**. Payments after the discount ends shrink by k·d.
- `g`: **variable cost per paid period** (e.g. AI compute), as a share of the list price. **ASSUMED**; the data has no
  costs, so the default is 0 (optimise revenue). A discount cuts the price but not this cost, so with g > 0 break-even
  rises, and a discount whose margin turns negative can never pay (break-even = ∞).
- With g = 0 the **store fee** cancels out and L*(d) = (1 / v_d − 1) / ρ, exactly the earlier revenue-only formula.

**Simplifications (stated in the app):** plan mix doesn't change with the discount; step-up churn is linear in d;
incremental buyers differ from ordinary ones only through ρ.

These formulas are validated independently in `tests/test_economics.py`. That includes hand-computed values, edge cases
(no discount, discount touches nothing, permanent price cut, negative margin), a by-hand cost example, and property tests
showing contribution at break-even equals full-price contribution for any inputs, fee and cost.

---

## 5. Customer response (ASSUMED)

A **bounded, diminishing-returns scenario curve**, not learned behaviour:

- A share `M = min(1, q × c₀)` of users is in-market (**market ceiling q**). So the largest possible relative lift is
  **below q − 1**, and lower still if capped at 100%.
- Their willingness to pay is **lognormal**. This is a modelling choice that the data doesn't identify. The curve is pinned so
  today's conversion equals the measured c₀, and its spread is solved from the user's answer to *"how much would a 20%
  discount lift conversion?"* (low / most likely / high).
- **Infeasible inputs are never clipped.** If the assumed lift can't fit under the ceiling, the app shows a clear
  error and asks the user to lower the range or raise the ceiling.
- **Uncertainty:** 4,000 draws of L₂₀ from a triangular distribution. Optionally (on by default) c₀ is drawn from its
  Jeffreys Beta posterior and V₀ from a normal with its standard error. The chart band states exactly which of these
  are included, and what isn't (ρ, k, q, the tail rule, the curve shape).

---

## 6. The recommendation: an experiment

Each discount up to the allowed maximum gets a verdict:

| Verdict | Meaning |
|---|---|
| **Worth testing** | beats full price in ≥ the chosen share of scenarios (default 50%) **and** its break-even lift can be detected within the max test length (default 8 weeks) |
| **Not plausible** | fails the first condition |
| **Too slow to test** | fails the second |

Among *Worth testing*, the discount with the highest expected revenue **under the selected assumptions** is
proposed. The headline says explicitly that it is *not a proven optimum*. Otherwise the app says:
**"Keep full price; don't spend traffic on a discount test yet"**, with the reason.

The **decision rule fixed before launch** includes:
- arms (control + discount; Bonferroni α split for several arms),
- users per arm and duration,
- randomisation (per user, persistent across visits and devices, only users reaching the placement, stratified by platform and price tier),
- primary metric (conversion to first paid receipt within 14 days),
- the rollout condition (significant **and** ≥ break-even conversion **and** guardrails hold),
- guardrails (net revenue per randomised user; refund rate),
- when to review renewal revenue (14 days + one period of the audience's main plan, then at the horizon),
- no peeking.

### Sample size and duration (CALCULATED)
- Two-sided **two-proportion z-test**, pooled variance under H₀, no continuity correction, α = 0.05 (÷ number of
  discount arms), power 80%, detecting c₀ → c₀ × (1 + L*(d)). Verified against the textbook case: **10% → 12% needs
  3,841 per arm**. A 20,000-run simulation confirms 80% power.
- **Duration** = users per arm ÷ (weekly eligible traffic × allocation ÷ number of groups) + 14-day outcome wait.
- **Traffic** is the selected audience's installs per observed week from the *dataset sample*, or a user-entered
  real figure (labelled ASSUMED).
- A **revenue-per-user** test size is also shown, from the measured revenue spread. It's much larger, which is why
  revenue is a guardrail, not the launch criterion.

### Results with default assumptions (computed at runtime, 12-month horizon, first paid payment discounted)
| Placement | Outcome |
|---|---|
| onboarding | **Worth testing: 35% off.** Break-even lift 34.2%; 751 users/arm; ~2.9 weeks; beats full price in 75% of scenarios |
| main | **Worth testing: 30% off.** Break-even 30.9%; 753 users/arm; ~4.0 weeks; 68% |
| ai_limit_reached | **Keep full price.** Annual-heavy, so the discount touches 100% of revenue; no discount is plausible enough |
| settings_upgrade | **Keep full price.** No discount clears the plausibility bar |
| win_back | **Keep full price.** Discounts look plausible, but no test fits in 8 weeks at 116 installs/week (and 52% of V₀ is extrapolated) |

---

## 7. Sensitivity

The **Sensitivity** tab shows how the best discount *under the assumptions* moves:

- **Switch points:** "if a 20% discount lifts conversion by X–Y%, the best discount is Z", over feasible lifts only.
  For `onboarding`, full price wins below a 17% lift.
- **Heatmap:** L₂₀ × a second assumption (market ceiling q, ρ or k). Cells that are impossible under the ceiling are
  marked ✕ rather than clipped.
- **Win frequency:** how often each discount is best across the selected L₂₀ range. For `onboarding` with defaults:
  full price 26%, 35% off 28%, 40% off 37%, others ~2% each. A wide spread is exactly why a test is needed.
- The best discount can **fall** at very high assumed lifts. A modest discount already reaches most of the market,
  so deeper ones mostly subsidise people who'd buy anyway. The app explains this.

---

## 8. The randomized tests in the data (a real finding)

The dataset contains three **randomized** A/B tests from the hackathon: users were randomly assigned to one of two
paywalls. The arms are balanced: they differ by at most 2.0 percentage points on platform, country and acquisition
channel. So their differences are **causal effects**, unlike every other comparison in the data. They change the
offer's *structure*, not its price.

| Test (placement) | Control → winner | Conversion | Revenue per install (12 mo) | Cash received so far |
|---|---|---|---|---|
| Onboarding: annual trial vs weekly first (`onboarding`) | `onb_trial` → **`onb_weekly`** | 11.3% → **22.3%** (+96%) | $5.36 → **$11.05** (+106%) | +84% |
| Settings: upgrade vs lifetime anchor (`settings_upgrade`) | `settings` → **`main_lifetime`** | 17.5% → **25.0%** (+43%) | $10.44 → **$15.75** (+51%) | +17% |
| Main (US/Canada): 3 plans vs lifetime anchor (`main`) | `main` → **`main_lifetime`** | 23.9% → **30.2%** (+26%) | $16.29 → **$22.25** (+37%) | +81% |

All three differences are significant (p < 0.001).

**What it means for discounts:**
1. **Offer structure beat any discount, at full price.** Changing the paywall raised conversion by 26–96% with no price
   cut. A 35% discount on onboarding only *breaks even* at +34%. So **test the paywall structure first, then discounts
   on the winning paywall.**
2. **It exposed a blend in our own recommendation.** The `onboarding` placement mixes the two test paywalls 50/50. The
   blended audience gives "test 35% off". On the winning `onb_weekly` paywall alone it's **test 40% off** (break-even
   36.7%, 456 users per group, about 3 weeks); on `onb_trial` alone it's 25%. The app now **warns** when an audience
   mixes paywalls, and *Segment filter → Flow (paywall)* gives the per-paywall answer.
3. **A reality check for the assumed response.** Our default guess (a 20% discount lifts conversion 5–50%) is in the
   same range as the offer changes this app's users responded to. It's still not a measurement of discount sensitivity.

**Caveats:** the data is synthetic, so the generator built these effects in. Revenue per install includes extrapolated
renewals; "cash received so far" is measured only. Code: `experiments.py`; app tab: **Randomized tests**;
tests: `tests/test_experiments.py`.

---

## 9. App tabs

| Tab | Content |
|---|---|
| **Recommendation** | headline · c₀ with CI, payers, V₀ (with extrapolated share), share touched, traffic · decision rule · per-discount table with verdicts · revenue curve with labelled band · break-even vs assumed chart · DATA / CALCULATED / ASSUMED input tables · test-size method |
| **Sensitivity** | switch points · heatmap · win frequency · saturation explanation |
| **Compare segments** | placements, or segments within the selected placement: payers, conversion with CI, V₀, extrapolated share, share touched, traffic, break-even, test candidate, users per arm, weeks. Cohorts under 30 payers are flagged and get no recommendation. Confounding caveat. |
| **Randomized tests** | the three randomized A/B tests in the data: conversion with CI, difference with CI and p-value, revenue per install, cash so far, plan mix, balance check, and what it means for discounts |
| **Baselines** | per-segment conversion with CI, payers, refund rate, observed vs expected revenue, extrapolated share, traffic · renewal curves (estimated vs extrapolated) · per-plan table (observed steps, 2nd payment, tail rate, refund rate) · plan mix · horizon warning |
| **Data reality check** | synthetic notice, cutoff, data semantics computed at runtime, contents vs gaps, regional price chart with confounding explanation |
| **Live Adapty** | the 5k and 50k Adapty apps vs the offline CSV for the same users (counts, refunds, cancellations, plan mix, revenue), plus the simulated discount test per arm with a significance check. Reads local snapshots only; never calls Adapty. |
| **Method** | definitions, censoring rules, formulas, assumptions, sample-size method, limits |

---

## 10. Code and tests

```
discount_advisor/
├── app.py                  Streamlit UI
├── data.py                 loading, cutoff, conversion window, chains, censoring, net receipts
├── metrics.py              measured baselines (no Streamlit)
├── economics.py            break-even, response curve, simulation, sensitivity, test plan (no Streamlit)
├── charts.py               Plotly figures
├── adapty_live.py          read-only download of seeded profiles from a live Adapty app (section 11)
├── build_seed_dataset.py   50k offline CSVs → seeder dataset format (section 11)
├── seed_50k.py             seeds a new Adapty app with all 50k users (section 11)
├── adapty_experiment.py    discount A/B test with simulated users in the live app (section 11)
├── live_view.py            Live Adapty tab: summaries from local snapshots (no network)
├── experiments.py          the randomized A/B tests in the data; blend detection (section 8)
├── DISCOUNT_FORMULA.md     how a discount is picked, with a worked example
├── DEMO_SCRIPT.md          3-minute demo script with the app's default numbers
├── .live_cache/            downloaded profiles + generated 50k dataset (no keys; not in git)
└── tests/
    ├── test_data.py        integrity, semantics, cutoff, censoring (incl. toy chains), maturity, refunds
    ├── test_metrics.py     conversion from raw, denominators, Wilson CI, horizons, KM (toy + real), tail rule,
    │                       refunds, V₀ brute force, revenue split, a by mix and horizon, segment totals, small cohorts
    ├── test_economics.py   formulas by hand and edge cases, fee consistency, feasibility (raise, never clip),
    │                       curve properties, simulation, sensitivity, textbook sample size, power, Bonferroni,
    │                       durations, plan verdicts and decision rule, variable cost
    ├── test_app.py         the real app driven headlessly through placements, segments, offers, horizons,
    │                       infeasible and degenerate assumptions, slider extremes, arms, fee, traffic override, selectors
    ├── test_live_view.py   Live Adapty tab logic on hand-made snapshots (offline)
    ├── test_experiments.py randomized tests: arms, lifts, p-values, balance, blend detection
    └── test_live_adapty.py live Adapty app vs offline data (skipped unless ADAPTY_LIVE=1; section 11)
```

See the README for run commands.

**Latest runs:**
- 2026-11-08, after adding the Randomized tests tab: `python -m pytest tests -q` → **188 passed, 24 skipped** in
  about 9 minutes. The 24 skipped are the live Adapty checks, which need `ADAPTY_LIVE=1`.
- 2026-11-07, live checks, 5,000-user app: **24 passed**.
- 2026-11-07, live checks, 50,000-user app: **22 passed, 2 skipped** (the skipped two check "installed today" users, which that app
  deliberately doesn't have).

Re-run after any change; these numbers are only valid for the code as of that date.

---

## 11. The live Adapty account

The Discount Advisor reads the offline CSVs. Separately, we seeded a real Adapty account with the same synthetic
population and checked that what Adapty stores matches what the advisor analyses.

### 11.1 Seeding the hackathon app (5,000 users)
- **Setup:** Node.js v24, Adapty CLI 0.18.0 (`npm install -g adapty@latest`), `adapty auth login`.
- **Windows fix in the hackathon repo:** `seed_adapty.py` started the CLI by the bare name `adapty`, which Python can't
  launch on Windows (npm installs it as `adapty.cmd`). Two lines in `Cli.__init__` now use the full path from
  `shutil.which`. On this PC, use `..\.venv\Scripts\python.exe`: `python3` is a Microsoft Store alias.
- **Run:** catalog first (`--skip-data`), then data (`--app-id … --skip-config`), with the secret key read from the
  logged-in CLI, never printed.
- **App:** *Lumen - AI Photo Editor (Hackathon)*, id `cc1f40d1-26c1-4f9d-8341-ba719971ac32`
  - 6 products, 7 published paywall flows, 3 segments, 5 placements
  - 4 demo A/B tests (2 live, 1 completed, 1 draft)
  - **6,000 profiles, 3,123 transactions, 0 failures.** That's 5,000 users with 4 months of history plus 1,000
    "installed today" copies.
- **Tracked revenue:** the seeder dates all of it before the app's first profile, which keeps it outside Adapty's
  monthly tracked revenue (MTR).

### 11.2 Live verification (5,000-user app)
All **6,000** profiles were downloaded (`adapty_live.py`, about 2 minutes, read-only) and compared with the offline data in
`tests/test_live_adapty.py`. **24 of 24 checks pass.**

| Check | Result |
|---|---|
| Every seeded profile exists, belongs to the app, carries the seed marker | ✅ 6,000 / 6,000 |
| Custom attributes (channel, goal, AI edits, photos, push, app version) | ✅ identical for all 5,000 |
| Store matches platform (iOS → App Store, Android → Play) | ✅ |
| Same users are buyers / trial users | ✅ 1,393 both sides |
| Store product IDs, cancellation reasons | ✅ identical |
| Time shift | ✅ one constant (404,772 s ≈ 4.7 days) explains every date |
| USD revenue | ✅ exact to the cent, **net of refunds** |
| "Installed today" users | ✅ copies of their source user; purchases dated today |
| Advisor-relevant aggregates | ✅ same conversion and plan mix as offline; the 5k sample sits inside the 50k population's confidence interval |

Three things that look like mismatches but are **how Adapty represents data**. The tests encode them:
- **Refunds:** a refunded receipt's expiry is set to its purchase time, and revenue drops to $0.
- **Lifetime:** listed as a subscription item **with no expiry**, not as a non-subscription.
- **Offers and currencies:** the profile shows the **latest** receipt's offer. Non-USD revenue is converted at Adapty's own
  exchange rates: revenue ÷ net local price is constant per currency (variation < 3.1%), against up to 30% when computed
  gross. So Adapty, like the Discount Advisor, treats a refunded receipt as $0.

### 11.3 Discount A/B test with simulated users (`adapty_experiment.py`)
A small end-to-end pipeline demo of what the advisor recommends.

**Created in the Lumen app, all marked *(test)*:**
- 3 products at 30% off (`lumen.annual_30off`, `lumen.monthly_30off`, `lumen.weekly_30off`)
- a copy of the *Main - 3 plans* paywall selling them
- a live 50/50 A/B test on placement `main`: *Discount test: main 30% off vs full price (test)*

**Simulated users:** 150 real `main` users from the offline file who aren't already in the app (index ≥ 5,000), from
outside the US and Canada, split 50/50 by hash.
- **Control** users replay their real outcome: a paid purchase within 14 days, sent today.
- **Discount** users get the same at 70% of the price, plus extra buyers matching the advisor's **assumed** lift at 30%
  off (+31%).

**Sent:** 150 profiles, 150 paywall views, 25 purchases, 0 errors.

- **Tracked revenue:** about **$582**, under the $5,000 free limit (see 11.5). The 4 original demo tests are untouched.
- **What it shows:** only that the pipeline works (products, paywall, A/B test, attribution). The discount arm's extra
  buyers come from the advisor's own assumption, so **the result can't validate any discount**.
- **What happened next (2026-11-08):** a cleanup step was started and interrupted. Before the interruption it had
  stopped the test and deleted 23 of the simulated users (2 buyers). It was restored the same day: the 23 users and their
  2 purchases were re-sent to the original test, so its results are complete again (150 users, 25 buyers; Adapty total
  $593.77 at its exchange rates). A completed test can't be restarted, so a **live copy**, *(test, copy)*, now runs on
  `main`.
- **Result, honestly read:** control 14/83 buyers (16.9%), discount 11/67 (16.4%), difference −0.5 points, p = 0.94.
  That's noise, as expected with 150 users: the advisor sizes such a test at about 750 per arm.

### 11.4 A second app with the full 50,000 users
- **`build_seed_dataset.py`** converts the 50,000-user CSVs into the seeder's format. Timestamps are relative to
  2026-11-03 00:12:04 UTC; timezone and currency are mapped from country. **Verified:** converting the first 5,000
  users reproduces the shipped dataset with **0 differences**.
- **`seed_50k.py`** runs the unmodified seeder into a **new** app: *Lumen 50k - AI Photo Editor (Hackathon)*, id
  `92ceed1c-9d18-4610-89fa-e94374cfe3a5`.
  - **No "installed today" users:** at 50k they'd carry about $18k of purchases dated today. Without them, the app
    holds only history dated before it existed, so **no new tracked revenue**.
  - **Result:** **50,000 profiles, 29,794 transactions, 0 failures.**
  - The run paused for about 70 minutes partway through (sleep or a lost connection) and resumed cleanly. A temporary
    keep-awake helper covered the rest; no power settings were changed.
- **Verification:** all 50,000 profiles downloaded (about 30 minutes) and checked. **22 passed, 2 skipped.** Total live
  revenue is $440.6k, against $429.7k from `price_usd`; the gap is Adapty's exchange rates.

### 11.5 Billing: what "tracked revenue" means here
- **No real money moved.** The products are fictional, so no one was charged and nothing can be.
- Adapty bills by **monthly tracked revenue (MTR)**: the value of purchases recorded in a month. It's **free up to
  $5,000 a month**; above that it charges about 1% or limits dashboard features.
- **Only the simulated discount test counts.** Its 25 purchases add about **$582** (control ≈ $339, 30% off ≈ $243,
  estimated from the dataset's USD prices; Adapty's exchange rates may differ slightly). Re-sending the 2 deleted
  purchases during the restore added about $34 more, possibly counted twice. That leaves roughly $4,300 of headroom this
  month, assuming no other app in the account tracks revenue.
- **Nothing else counts:** the 5k app's history and "today's users", and all of the 50k app, are dated before each app
  existed.
- **Nothing accumulates.** The simulated subscriptions can't renew without a real store, so the total stays at about $582
  unless more purchases are sent.
- **Rule from here on:** nothing that adds tracked revenue or could cost money is run without asking first.

### 11.6 Current state and housekeeping
- **Everything is kept** (decided 2026-11-08): both apps keep all their data; the original discount test is *completed*
  with all 150 simulated users, and its live copy runs on `main`. The 4 original demo tests are unchanged.
- **Rotate the Lumen app's secret key**, because it was pasted in chat once: App settings → General. The Adapty CLI
  can't rotate keys, and the scripts read the current key from the CLI, so nothing breaks.
- **Git:** `discount_advisor/` is part of the team repository `DMustache/adapty-hack` on `main` (merged from the
  `model-implementation` branch; `.live_cache/` is not committed). The 2-line Windows fix to the hackathon seeder
  stays on a local branch `windows-cli-fix` of the organisers' repo (it can't be pushed there).
- **Related work in the same repo:** temporal churn model (`docs/TEMPORAL_CHURN.md`), usage-data support
  (`docs/USAGE_FEATURES.md`), full summary (`docs/PROJECT_SUMMARY.md`).
- **Not finished:** the pitch slide deck was started (4 of 9 slides, a private claude.ai artifact) and then dropped.
  `DEMO_SCRIPT.md` covers the demo.

---

## 12. Limitations

- **Synthetic data**: findings describe the generated *Lumen* dataset, not real customers.
- **Customer response is assumed**, and identical for all segments. Only an experiment can measure it.
- **The lognormal curve shape, ρ, k and q are modelling assumptions**, varied in the Sensitivity tab but not
  included in the uncertainty band.
- **Short history**: annual renewals are unobservable; weekly and monthly revenue beyond the observed periods is extrapolated.
- **Costs are an assumption**: the data has none. The variable-cost input (default 0) is a flat share of list price;
  acquisition cost is not modelled (it's sunk by the time a user sees the paywall).
- **Traffic is a sample**: use the override for real durations.
- **Plan mix is held fixed** under a discount.
- **The live discount test uses simulated users** whose response comes from the advisor's own assumption. It shows the
  pipeline works, not that a discount works.
- **Live revenue differs from `price_usd`** for non-USD users, because Adapty applies its own exchange rates. The advisor uses
  the dataset's `price_usd`.

## 13. Next steps
1. Run the proposed test with **real** traffic as an Adapty paywall A/B test on the chosen placement, then replace L₂₀
   with the measured lift.
2. Feed the advisor from live Adapty data instead of the offline CSVs. Profiles (what `adapty_live.py` downloads) only
   carry each user's *latest* receipt, which is enough for the Live Adapty comparison but not for renewal curves. Those
   need the full receipt history, e.g. from Adapty's event exports or webhooks.
3. Replace the flat variable-cost assumption with real cost data (AI compute per active user, support), and add
   acquisition cost if the offer is shown at acquisition time.
4. Build per-segment response priors once several experiments exist.
