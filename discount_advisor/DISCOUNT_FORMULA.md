# How the Discount Advisor picks a discount

There's no single formula that outputs "the discount". The tool works in three steps:

1. **Calculate** what each discount must achieve. This is exact, from the data.
2. **Assume** how customers might react. This is your input, with a range.
3. **Pick** the discount worth *testing*, or say "keep full price".

---

## Step 1: what each discount must achieve (exact, from the data)

### Inputs (per audience)

| Symbol | Meaning | Where it comes from |
|---|---|---|
| c₀ | baseline conversion: share of installs that pay within 14 days | **measured** |
| V₀ | expected revenue per payer over the horizon (after refunds) | **measured** (renewal curves) |
| a | share of that revenue the discount touches | **measured** (plan mix × renewal curves) |
| d | the discount, e.g. 0.35 = 35% off | you choose |
| k | extra cancellations when the full price returns ("step-up churn") | **assumed**, default 0.3 |
| ρ | value of a discount-driven buyer vs a regular one (deal-seekers renew less) | **assumed**, default 0.85 |

### What a payer is worth after the discount (share of V₀)

```
v_d = (1 − d) × a  +  (1 − a) × (1 − k × d)
```

- **(1 − d) × a**: the payments during the discount, now at the lower price.
- **(1 − a) × (1 − k × d)**: the later full-price payments, minus the extra cancellations.

### Break-even lift

The relative increase in conversion a discount needs just to break even:

```
L* = (1 / v_d − 1) / ρ
```

Conversion needed = c₀ × (1 + L*).

### Worked example: onboarding, 35% off the first payment

Inputs: a = 0.49, k = 0.3, ρ = 0.85, c₀ = 16.8%

```
v_d = 0.65 × 0.49  +  0.51 × (1 − 0.3 × 0.35)
    = 0.3185 + 0.4565
    = 0.775            → every payer is now worth 77.5% as much

L*  = (1 / 0.775 − 1) / 0.85
    = 0.290 / 0.85
    = 34.2%

Conversion needed = 16.8% × 1.342 ≈ 22.5%
```

So 35% off only pays if conversion rises from **16.8% to at least 22.5%**.

### Optional: with costs

If you set a variable cost per paid period **g** (e.g. AI compute, as a share of list price), the tool uses the margin
after the store fee and cost instead of revenue:

```
payments kept  P_d = a + (1 − a) × (1 − k × d)
margin         m_d = (1 − fee) × v_d − g × P_d
break-even     L*  = (m₀ / m_d − 1) / ρ
```

A discount cuts the price but not the cost, so break-even rises. If m_d ≤ 0, no increase in conversion can ever pay
for the discount. With g = 0 (the default) the store fee cancels out and you get the simple formula above.

---

## Step 2: how customers might react (assumed, not measured)

The data contains **no discount offers**, so customer reaction can't be measured. You answer one question:

> **How much would a 20% discount raise conversion?** low / most likely / high (default 5% / 20% / 50%)

The tool turns that answer into a curve c(d), the conversion at discount d:
- **Diminishing returns:** each extra 5% of discount brings fewer new buyers.
- **Market ceiling q:** conversion can never exceed q × c₀ (default 2×); not every user is a potential buyer.
- **Pinned to reality:** at 0% discount the curve gives exactly today's measured conversion.

The tool draws **4,000 scenarios** from your low / most-likely / high range.

### Revenue per user shown the offer

```
R(d) = V₀ × [ c₀ × v_d  +  (c(d) − c₀) × ρ × v_d ]
```

- **c₀ × v_d**: existing buyers, now paying less (cannibalisation).
- **(c(d) − c₀) × ρ × v_d**: the new buyers the discount brings in.

(The store fee multiplies everything equally; with costs, v_d becomes the margin m_d.)

---

## Step 3: picking the discount to test

For each discount from 5% up to the maximum you allow (default 40%):

1. **Plausible?** Does it beat full price in at least half of the 4,000 scenarios?
2. **Testable?** Can an A/B test detect its break-even lift within 8 weeks at this audience's traffic?

| Verdict | Meaning |
|---|---|
| **Worth testing** | passes both checks |
| **Not plausible** | fails check 1 |
| **Too slow to test** | fails check 2 |

Among the discounts that are worth testing, the tool picks the one with the **highest expected revenue**. If none
passes, it says **"Keep full price; don't spend traffic on a discount test yet."**

### Test size

Users per group come from a standard two-proportion test (5% significance, 80% power), sized to detect the
break-even lift. That's the smallest improvement worth finding.

### Results with default settings (12-month horizon, discount on the first paid payment)

| Placement | Outcome |
|---|---|
| onboarding | **Test 35% off**: break-even 34.2%, 751 users per group, ≈ 3 weeks |
| main | **Test 30% off**: break-even 30.9%, 753 users per group, ≈ 4 weeks |
| ai_limit_reached | **Keep full price**: annual plans, so the discount hits all revenue |
| settings_upgrade | **Keep full price**: no discount is plausible enough |
| win_back | **Keep full price**: too little traffic to test in 8 weeks |

---

## The bottom line

- **Exact:** the break-even numbers (e.g. 35% off needs conversion to rise by 34.2%). They come from measured data.
- **Unknown:** whether customers will actually react that strongly. That's an assumption.
- **So:** the tool says *test it*, not *use it*, and it tells you how big the test must be.

Code: `economics.py` (`value_factor`, `margin_factor`, `break_even_lift`, `conversion_at`, `simulate`, `plan_test`).
Full details: `PROJECT_OVERVIEW.md`, sections 4–6.
