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
V_d   = V₀ × [ (1 − d) × a  +  (1 − a) × (1 − k × d) ]
R(d)  = ( c₀ × V_d  +  (c(d) − c₀) × ρ × V_d ) × (1 − fee)
L*(d) = (V₀ / V_d − 1) / ρ            ← break-even relative conversion lift
```

- `c₀ × V_d`: existing payers now pay less (**cannibalisation**).
- `(c(d) − c₀) × ρ × V_d`: new payers, worth ρ of an ordinary payer.
- `k`: **step-up churn**. Payments after the discount ends shrink by k·d.
- The **store fee** multiplies baseline and discounted revenue alike, so it never changes break-even.

**Simplifications (stated in the app):** plan mix doesn't change with the discount; step-up churn is linear in d;
incremental buyers differ from ordinary ones only through ρ.

These formulas are validated independently in `tests/test_economics.py`. That includes hand-computed values, edge cases
(no discount, discount touches nothing, permanent price cut), and a property test showing revenue at break-even equals
full-price revenue for any inputs and fee.

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

## 8. App tabs

| Tab | Content |
|---|---|
| **Recommendation** | headline · c₀ with CI, payers, V₀ (with extrapolated share), share touched, traffic · decision rule · per-discount table with verdicts · revenue curve with labelled band · break-even vs assumed chart · DATA / CALCULATED / ASSUMED input tables · test-size method |
| **Sensitivity** | switch points · heatmap · win frequency · saturation explanation |
| **Compare segments** | placements, or segments within the selected placement: payers, conversion with CI, V₀, extrapolated share, share touched, traffic, break-even, test candidate, users per arm, weeks. Cohorts under 30 payers are flagged and get no recommendation. Confounding caveat. |
| **Baselines** | per-segment conversion with CI, payers, refund rate, observed vs expected revenue, extrapolated share, traffic · renewal curves (estimated vs extrapolated) · per-plan table (observed steps, 2nd payment, tail rate, refund rate) · plan mix · horizon warning |
| **Data reality check** | synthetic notice, cutoff, data semantics computed at runtime, contents vs gaps, regional price chart with confounding explanation |
| **Method** | definitions, censoring rules, formulas, assumptions, sample-size method, limits |

---

## 9. Code and tests

```
discount_advisor/
├── app.py          Streamlit UI
├── data.py         loading, cutoff, conversion window, chains, censoring, net receipts
├── metrics.py      measured baselines (no Streamlit)
├── economics.py    break-even, response curve, simulation, sensitivity, test plan (no Streamlit)
├── charts.py       Plotly figures
└── tests/
    ├── test_data.py        integrity, semantics, cutoff, censoring (incl. toy chains), maturity, refunds
    ├── test_metrics.py     conversion from raw, denominators, Wilson CI, horizons, KM (toy + real), tail rule,
    │                       refunds, V₀ brute force, revenue split, a by mix and horizon, segment totals, small cohorts
    ├── test_economics.py   formulas by hand and edge cases, fee consistency, feasibility (raise, never clip),
    │                       curve properties, simulation, sensitivity, textbook sample size, power, Bonferroni,
    │                       durations, plan verdicts and decision rule
    └── test_app.py         the real app driven headlessly through placements, segments, offers, horizons,
                            infeasible and degenerate assumptions, slider extremes, arms, fee, traffic override, selectors
```

See the README for run commands.

**Latest run (2026-11-07):** `python -m pytest tests -q` → **158 passed** in about 5½ minutes (all four files,
including the end-to-end app sweep). Re-run after any change; this number is only valid for the code as of that date.

---

## 10. Limitations

- **Synthetic data**: findings describe the generated *Lumen* dataset, not real customers.
- **Customer response is assumed**, and identical for all segments. Only an experiment can measure it.
- **The lognormal curve shape, ρ, k and q are modelling assumptions**, varied in the Sensitivity tab but not
  included in the uncertainty band.
- **Short history**: annual renewals are unobservable; weekly and monthly revenue beyond the observed periods is extrapolated.
- **Revenue, not profit**: no acquisition or compute costs.
- **Traffic is a sample**: use the override for real durations.
- **Plan mix is held fixed** under a discount.

## 11. Next steps
1. Run the proposed test as an Adapty paywall A/B test on the chosen placement, then replace L₂₀ with the measured lift.
2. Add costs to optimise profit.
3. Build per-segment response priors once several experiments exist.
