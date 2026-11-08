"""Discount economics: exact break-even arithmetic + an explicitly ASSUMED scenario response curve.

Notation (per eligible user shown the offer):
    c0   baseline conversion                                                    [DATA]
    V0   expected net-of-refund revenue per payer over the horizon, at full price [DATA + tail rule]
    a    share of V0 that the discount touches (plan mix x renewal curves)       [DATA]
    d    discount, 0..1
    rho  value of an *incremental* (discount-driven) payer vs an ordinary payer   [ASSUMED]
    k    step-up churn: payments after the discount ends shrink by k*d           [ASSUMED]
    q    market ceiling: max conversion = min(1, q*c0)                            [ASSUMED]
    L20  relative conversion lift from a 20% discount (low / most likely / high)  [ASSUMED]
    fee  store commission, applied identically to baseline and discounted revenue
    g    variable cost per paid period (e.g. AI compute) as a share of the full list price  [ASSUMED, default 0]

    Per payer, as a share of V0 (list-price revenue over the horizon):
      payments kept   P_d = a + (1 - a) * (1 - k * d)                    (step-up churn removes later payments)
      revenue kept    v_d = (1 - d) * a + (1 - a) * (1 - k * d)          (every payer pays less: cannibalisation)
      margin          m_d = (1 - fee) * v_d - g * P_d                    (the discount cuts price, not cost)
    R(d)  = V0 * (c0 * m_d + (c(d) - c0) * rho * m_d)                     net contribution per eligible user
    L*(d) = (m_0 / m_d - 1) / rho                                       break-even relative lift   [CALCULATED]
    With g = 0 the fee cancels and L*(d) = (1 / v_d - 1) / rho. If m_d <= 0 the discount can never pay (L* = inf).

Simplifications: the discount does not change who among the *existing* payers buys which plan (plan mix fixed);
step-up churn is linear in d; incremental payers differ from ordinary ones only through the factor rho.

Response curve c(d) is a SCENARIO MODEL, not learned behaviour (the data has no discount exposure):
    a share M = min(1, q*c0) of users is "in market"; their willingness-to-pay is lognormal with spread sigma,
    located so that M * P(WTP >= list price) = c0. Then c(d) = M * (1 - Phi(z0 + ln(1 - d) / sigma)),
    z0 = Phi^-1(1 - c0 / M). sigma is solved from L20. A lift >= M / c0 - 1 cannot be produced by any sigma:
    such inputs raise InfeasibleAssumption instead of being clipped.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
import pandas as pd
from scipy.stats import beta as beta_dist
from scipy.stats import norm

DISCOUNT_GRID = np.round(np.arange(0.0, 0.55, 0.05), 2)
ANCHOR_DISCOUNT = 0.20


class InfeasibleAssumption(ValueError):
    """An assumed lift cannot be produced under the chosen market ceiling."""


# --------------------------------------------------------------------------- exact arithmetic

def value_factor(d, a: float, k: float = 0.0) -> np.ndarray:
    """V_d / V0."""
    d = np.asarray(d, dtype=float)
    return (1 - d) * a + (1 - a) * np.clip(1 - k * d, 0, 1)


def payments_factor(d, a: float, k: float = 0.0) -> np.ndarray:
    """Share of full-price payments still made after the discount (step-up churn)."""
    d = np.asarray(d, dtype=float)
    return a + (1 - a) * np.clip(1 - k * d, 0, 1)


def margin_factor(d, a: float, k: float = 0.0, fee: float = 0.0, cost: float = 0.0) -> np.ndarray:
    """Contribution per payer as a share of V0: revenue after fee minus variable cost per paid period."""
    return (1 - fee) * value_factor(d, a, k) - cost * payments_factor(d, a, k)


def break_even_lift(d, a: float, rho: float = 1.0, k: float = 0.0, fee: float = 0.0, cost: float = 0.0) -> np.ndarray:
    """Relative conversion lift at which R(d) == R(0). With cost = 0 the store fee cancels out.
    Returns inf where the discounted margin is not positive (no lift can pay for it)."""
    m0 = margin_factor(0.0, a, k, fee, cost)
    md = margin_factor(d, a, k, fee, cost)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = (m0 / md - 1) / rho
    return np.where(md > 0, out, np.inf)


# --------------------------------------------------------------------------- assumed response curve

def market_size(c0: float, q: float) -> float:
    return float(min(1.0, q * c0))


def max_feasible_lift(c0, q: float):
    """Largest relative lift the ceiling allows: min(1, q*c0)/c0 - 1 (strictly unreachable, a supremum)."""
    c0 = np.asarray(c0, dtype=float)
    return np.minimum(1.0, q * c0) / c0 - 1


def check_feasible(c0, lifts, q: float) -> None:
    lifts = np.asarray(lifts, dtype=float)
    if q <= 1:
        raise InfeasibleAssumption(f"Market ceiling q must be > 1 (got {q}).")
    if np.any(lifts < 0):
        raise InfeasibleAssumption("Assumed lifts must be >= 0.")
    bad = lifts >= max_feasible_lift(c0, q) - 1e-9
    if np.any(bad):
        mx = float(np.min(np.broadcast_to(max_feasible_lift(c0, q), bad.shape)[bad]))
        raise InfeasibleAssumption(
            f"An assumed lift of {float(np.max(lifts)):.0%} is impossible with a market ceiling of {q:g}× baseline: "
            f"conversion can rise by less than {mx:.0%} at most. Lower the lift range or raise the ceiling.")


def sigma_from_anchor(c0, lift_at_anchor, q: float, anchor: float = ANCHOR_DISCOUNT) -> np.ndarray:
    """Spread of log-WTP implied by 'a 20% discount lifts conversion by <lift>'. lift = 0 -> inf (no response)."""
    c0 = np.asarray(c0, dtype=float)
    lift = np.asarray(lift_at_anchor, dtype=float)
    check_feasible(c0, lift, q)
    m = np.minimum(1.0, q * c0)
    c1 = c0 * (1 + lift)
    with np.errstate(divide="ignore", invalid="ignore"):
        sig = np.log(1 - anchor) / (norm.ppf(1 - c1 / m) - norm.ppf(1 - c0 / m))
    return np.where(lift <= 0, np.inf, sig)


def conversion_at(d, c0, sigma, q: float) -> np.ndarray:
    c0 = np.asarray(c0, dtype=float)
    m = np.minimum(1.0, q * c0)
    d = np.asarray(d, dtype=float)
    sigma = np.asarray(sigma, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        shift = np.where(np.isinf(sigma), 0.0, np.log1p(-d) / sigma)
    return m * norm.sf(norm.ppf(1 - c0 / m) + shift)


def revenue_per_user(d, c0, v0, a: float, sigma, q: float, rho: float = 1.0, k: float = 0.0,
                     store_fee: float = 0.0, cost: float = 0.0) -> np.ndarray:
    """Net contribution per eligible user (= net revenue when cost = 0)."""
    c = conversion_at(d, c0, sigma, q)
    md = np.asarray(v0, dtype=float) * margin_factor(d, a, k, store_fee, cost)
    return c0 * md + (c - c0) * rho * md


# --------------------------------------------------------------------------- simulation

@dataclass
class Assumptions:
    lift_low: float = 0.05
    lift_mode: float = 0.20
    lift_high: float = 0.50
    rho: float = 0.85
    k: float = 0.3
    q: float = 2.0
    store_fee: float = 0.15
    cost: float = 0.0               # variable cost per paid period, share of list price (0 = revenue only)
    include_sampling: bool = True   # also draw c0 and V0 from their sampling distributions
    n_draws: int = 4000
    seed: int = 7

    def validate(self) -> list[str]:
        errs = []
        if not (0 <= self.lift_low <= self.lift_mode <= self.lift_high):
            errs.append("Lift assumptions must satisfy 0 ≤ low ≤ most likely ≤ high.")
        if self.q <= 1:
            errs.append("Market ceiling must be above 1× baseline.")
        if not (0 < self.rho <= 1):
            errs.append("ρ must be in (0, 1].")
        if not (0 <= self.k <= 1):
            errs.append("k must be in [0, 1].")
        if not (0 <= self.store_fee < 1):
            errs.append("Store fee must be in [0, 1).")
        if not (0 <= self.cost < 1 - self.store_fee):
            errs.append("Variable cost must be ≥ 0 and leave a positive margin at full price (cost < 1 − fee).")
        return errs


@dataclass
class Measured:
    """Measured inputs plus what is needed to describe their sampling uncertainty."""
    c0: float
    v0: float
    a: float
    installs: int = 0
    payers: int = 0
    v0_se: float = 0.0


def _draw_lifts(asm: Assumptions, rng) -> np.ndarray:
    if asm.lift_high - asm.lift_low < 1e-9:
        return np.full(asm.n_draws, asm.lift_mode)
    return rng.triangular(asm.lift_low, asm.lift_mode, asm.lift_high, size=asm.n_draws)


def _draw_measured(m: Measured, asm: Assumptions, rng):
    if not (asm.include_sampling and m.installs > 0):
        return np.full(asm.n_draws, m.c0), np.full(asm.n_draws, m.v0)
    a_, b_ = m.payers + 0.5, m.installs - m.payers + 0.5            # Jeffreys posterior for c0
    lo, hi = beta_dist.ppf([0.0005, 0.9995], a_, b_)
    c0s = np.clip(rng.beta(a_, b_, size=asm.n_draws), lo, hi)       # truncate the extreme 0.1%
    v0s = np.maximum(rng.normal(m.v0, m.v0_se, size=asm.n_draws), 0.01) if m.v0_se > 0 else np.full(asm.n_draws, m.v0)
    return c0s, v0s


def interval_label(asm: Assumptions) -> str:
    return ("90% interval: response assumption (L₂₀) + sampling uncertainty of c₀ and V₀"
            if asm.include_sampling else "90% interval: response assumption (L₂₀) only; c₀ and V₀ fixed")


def simulate(m: Measured, asm: Assumptions, grid=DISCOUNT_GRID) -> pd.DataFrame:
    """Monte Carlo over the L20 assumption (triangular) and optionally over measured c0 / V0.

    Raises InfeasibleAssumption if any drawn lift is impossible under the ceiling for the drawn c0.
    """
    errs = asm.validate()
    if errs:
        raise InfeasibleAssumption(" ".join(errs))
    rng = np.random.default_rng(asm.seed)
    lifts = _draw_lifts(asm, rng)
    c0s, v0s = _draw_measured(m, asm, rng)
    sigma = sigma_from_anchor(c0s, lifts, asm.q)
    sigma_mode = sigma_from_anchor(m.c0, asm.lift_mode, asm.q)
    m0 = float(margin_factor(0.0, m.a, asm.k, asm.store_fee, asm.cost))
    base_draws = c0s * v0s * m0
    base = m.c0 * m.v0 * m0
    rows = []
    for d in grid:
        r = revenue_per_user(d, c0s, v0s, m.a, sigma, asm.q, asm.rho, asm.k, asm.store_fee, asm.cost)
        lift_d = conversion_at(d, c0s, sigma, asm.q) / c0s - 1
        rows.append({
            "discount": d,
            "rev_mean": r.mean(), "rev_p05": np.quantile(r, 0.05), "rev_p95": np.quantile(r, 0.95),
            "uplift_vs_base": r.mean() / base_draws.mean() - 1 if base else np.nan,
            "p_beats_base": float((r > base_draws * (1 + 1e-9)).mean()) if d > 0 else np.nan,
            "breakeven_lift": float(break_even_lift(d, m.a, asm.rho, asm.k, asm.store_fee, asm.cost)),
            "assumed_lift_mode": float(conversion_at(d, m.c0, sigma_mode, asm.q) / m.c0 - 1),
            "assumed_lift_p05": float(np.quantile(lift_d, 0.05)),
            "assumed_lift_p95": float(np.quantile(lift_d, 0.95)),
            "revenue_per_payer": float(m.v0 * margin_factor(d, m.a, asm.k, asm.store_fee, asm.cost)),
        })
    df = pd.DataFrame(rows)
    df.attrs["baseline_rev"] = base
    df.attrs["interval_label"] = interval_label(asm)
    return df


# --------------------------------------------------------------------------- sample sizes

def ab_sample_size(c0: float, lift: float, alpha: float = 0.05, power: float = 0.8, comparisons: int = 1) -> int:
    """Users per arm, two-sided two-proportion z-test (pooled variance under H0, no continuity correction)
    detecting c0 -> c0 * (1 + lift). With several discount arms, alpha is Bonferroni-split across comparisons."""
    p1, p2 = c0, c0 * (1 + lift)
    if lift <= 0 or p2 >= 1 or p1 <= 0:
        return 0
    a = alpha / max(1, comparisons)
    z_a, z_b = norm.ppf(1 - a / 2), norm.ppf(power)
    pbar = (p1 + p2) / 2
    n = (z_a * np.sqrt(2 * pbar * (1 - pbar)) + z_b * np.sqrt(p1 * (1 - p1) + p2 * (1 - p2))) ** 2 / (p2 - p1) ** 2
    return int(np.ceil(n))


def revenue_sample_size(sd: float, delta: float, alpha: float = 0.05, power: float = 0.8) -> int:
    """Users per arm for a two-sided z-test on mean revenue per user detecting an absolute difference delta."""
    if delta <= 0 or sd <= 0:
        return 0
    z_a, z_b = norm.ppf(1 - alpha / 2), norm.ppf(power)
    return int(np.ceil(2 * (z_a + z_b) ** 2 * sd ** 2 / delta ** 2))


def duration_weeks(n_per_arm: int, weekly_eligible: float, allocation: float, arms: int, wait_days: float) -> float:
    """Enrolment time for (arms + 1) equal groups, plus the outcome waiting period for the last users enrolled."""
    per_group_week = weekly_eligible * allocation / (arms + 1)
    if per_group_week <= 0:
        return float("inf")
    return n_per_arm / per_group_week + wait_days / 7


# --------------------------------------------------------------------------- sensitivity

def best_discount(c0: float, v0: float, a: float, lift: float, asm: Assumptions, grid=DISCOUNT_GRID) -> float:
    """Contribution-maximising discount *under these exact assumptions* (no uncertainty). NaN if infeasible."""
    try:
        sigma = sigma_from_anchor(c0, lift, asm.q)
    except InfeasibleAssumption:
        return float("nan")
    r = revenue_per_user(grid, c0, v0, a, sigma, asm.q, asm.rho, asm.k, asm.store_fee, asm.cost)
    i = int(np.argmax(r))
    return float(grid[i]) if r[i] > r[0] * (1 + 1e-9) else 0.0


optimal_discount = best_discount  # backwards-compatible name

SENSITIVITY_PARAMS = {
    "q": "Market ceiling (q × baseline)",
    "rho": "Value of discount-driven buyer (ρ)",
    "k": "Step-up churn (k)",
}
SENSITIVITY_VALUES = {
    "rho": [0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
    "k": [0.0, 0.15, 0.3, 0.5, 0.75, 1.0],
    "q": [1.25, 1.5, 2.0, 3.0, 4.0, 5.0],
}
LIFT_SWEEP = np.round(np.arange(0.0, 1.01, 0.05), 2)


def sensitivity_grid(c0: float, v0: float, a: float, asm: Assumptions, param: str, grid=DISCOUNT_GRID) -> pd.DataFrame:
    """Best discount for every (L20) x (second assumption). Infeasible cells are NaN, never clipped."""
    rows = []
    for val in sorted(set(SENSITIVITY_VALUES[param]) | {round(float(getattr(asm, param)), 4)}):
        local = replace(asm, **{param: val})
        for lift in LIFT_SWEEP:
            rows.append({param: val, "lift_at_20": lift, "best_discount": best_discount(c0, v0, a, lift, local, grid)})
    return pd.DataFrame(rows)


def switch_points(c0: float, v0: float, a: float, asm: Assumptions, grid=DISCOUNT_GRID, step: float = 0.01,
                  max_lift: float = 1.5) -> pd.DataFrame:
    """Ranges of L20 over which each discount is best, over the feasible lifts only."""
    top = min(max_lift, float(max_feasible_lift(c0, asm.q)) - step)
    lifts = np.round(np.arange(0.0, top + 1e-9, step), 4)
    best = [best_discount(c0, v0, a, l, asm, grid) for l in lifts]
    rows, start = [], 0
    for i in range(1, len(lifts) + 1):
        if i == len(lifts) or best[i] != best[start]:
            rows.append({"best_discount": best[start], "lift_from": lifts[start], "lift_to": lifts[i - 1]})
            start = i
    out = pd.DataFrame(rows)
    out.attrs["max_feasible_lift"] = float(max_feasible_lift(c0, asm.q))
    return out


def win_frequency(c0: float, v0: float, a: float, asm: Assumptions, step: float = 0.01) -> pd.Series:
    """Share of an evenly-spaced sweep over [L20 low, L20 high] in which each discount is best."""
    lifts = np.arange(asm.lift_low, asm.lift_high + 1e-9, step) if asm.lift_high > asm.lift_low else [asm.lift_low]
    best = pd.Series([best_discount(c0, v0, a, float(l), asm) for l in lifts])
    return best.value_counts(normalize=True).sort_index()


# --------------------------------------------------------------------------- experiment plan

VERDICTS = ("Worth testing", "Not plausible", "Too slow to test")


@dataclass
class Experiment:
    weekly_eligible: float
    allocation: float = 1.0
    arms: int = 1                 # discount arms (plus one full-price control)
    max_weeks: float = 8
    min_plausibility: float = 0.5
    max_discount: float = 0.4
    wait_days: float = 14         # outcome window: conversion is judged 14 days after enrolment
    review_days: float = 21       # first renewal-revenue review (window + one period of the dominant plan)
    alpha: float = 0.05
    power: float = 0.8
    traffic_source: str = "dataset sample"


@dataclass
class TestPlan:
    table: pd.DataFrame
    test_discount: float          # 0 = don't test
    headline: str
    decision_rule: str


def plan_test(sim: pd.DataFrame, c0: float, exp: Experiment, rev_sd: float | None = None) -> TestPlan:
    """A discount is worth testing if it beats full price in >= min_plausibility of scenarios AND a test can
    detect its break-even lift within max_weeks. The plan picks the best expected revenue among those."""
    base = sim.attrs["baseline_rev"]
    rows = []
    for _, r in sim[(sim.discount > 0) & (sim.discount <= exp.max_discount + 1e-9)].iterrows():
        n = ab_sample_size(c0, r.breakeven_lift, exp.alpha, exp.power, exp.arms)
        weeks = duration_weeks(n, exp.weekly_eligible, exp.allocation, exp.arms, exp.wait_days) if n else float("inf")
        n_rev = (revenue_sample_size(rev_sd, r.uplift_vs_base * base, exp.alpha / exp.arms, exp.power) or None) \
            if rev_sd else None
        if r.p_beats_base < exp.min_plausibility:
            verdict = "Not plausible"
        elif weeks > exp.max_weeks:
            verdict = "Too slow to test"
        else:
            verdict = "Worth testing"
        rows.append({"discount": r.discount, "breakeven_lift": r.breakeven_lift,
                     "breakeven_conv": c0 * (1 + r.breakeven_lift), "assumed_lift_mode": r.assumed_lift_mode,
                     "p_beats_base": r.p_beats_base, "uplift_vs_base": r.uplift_vs_base, "n_per_arm": n if n else np.nan,
                     "weeks": weeks, "n_per_arm_revenue": n_rev, "verdict": verdict})
    t = pd.DataFrame(rows, columns=["discount", "breakeven_lift", "breakeven_conv", "assumed_lift_mode", "p_beats_base",
                                    "uplift_vs_base", "n_per_arm", "weeks", "n_per_arm_revenue", "verdict"])
    ok = t[t.verdict == "Worth testing"]
    if ok.empty:
        if t.empty:
            why = "No discount level is allowed by the maximum discount."
        elif (t.verdict == "Not plausible").all():
            why = (f"No discount beats full price in at least {exp.min_plausibility:.0%} of the simulated scenarios "
                   "under your assumptions.")
        else:
            why = (f"The discounts that might win can't be confirmed within {exp.max_weeks:g} weeks at "
                   f"{exp.weekly_eligible * exp.allocation:,.0f} eligible users/week ({exp.traffic_source}).")
        return TestPlan(t, 0.0, "**Keep full price; don't spend traffic on a discount test yet.** " + why, "")
    best = ok.loc[ok.uplift_vs_base.idxmax()]
    a_adj = exp.alpha / exp.arms
    headline = (f"**Worth testing: {best.discount:.0%} off vs full price.** This is the discount with the highest "
                f"expected revenue *under your assumptions* among those that can be tested in time. It is not a proven "
                f"optimum. It only pays off if conversion rises by at least **{best.breakeven_lift:.1%} relative** "
                f"({c0:.1%} → {best.breakeven_conv:.1%}); your assumptions put that at {best.p_beats_base:.0%} likely.")
    rule = f"""
**Fix before launch:**
- **Arms:** full-price control vs {best.discount:.0%} off{"" if exp.arms == 1 else f" (+{exp.arms - 1} other discount arm(s); α split by Bonferroni → {a_adj:.3f} per comparison)"}.
- **Sample:** {best.n_per_arm:,} users per arm; about {best.weeks:.1f} weeks at {exp.weekly_eligible * exp.allocation:,.0f} eligible users/week ({exp.traffic_source}). That includes {exp.wait_days:g} days for the last users enrolled to convert.
- **Randomisation:** per user, persistent (same arm on every visit and device, e.g. by Adapty profile), only users reaching this placement, stratified by platform and price tier.
- **Primary metric:** conversion to a first *paid* receipt within {exp.wait_days:g} days of first exposure. Two-sided test at α = {a_adj:.3f}, power {exp.power:.0%}.
- **Roll out only if** conversion in the discount arm is significantly higher **and** its point estimate is ≥ {best.breakeven_conv:.1%} (break-even) **and** the guardrails hold.
- **Guardrails:** net revenue per randomised user (after refunds and store fee) not significantly below control; refund rate not above control by more than 1 percentage point.
- **Renewal review:** at day {exp.review_days:g} (first full-price renewal of the main plan) compare renewal rates, then again at the end of the revenue horizon. Renewal behaviour (ρ, k) is assumed in this plan, not tested.
- **No peeking:** don't stop early on a good-looking interim result.
"""
    return TestPlan(t, float(best.discount), headline, rule)
