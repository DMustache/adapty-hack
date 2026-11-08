"""Economics: exact formulas, response-curve feasibility, simulation, sensitivity, test sizing and plans."""
import numpy as np
import pandas as pd
import pytest
from hypothesis import assume, given, settings, strategies as st

from economics import (DISCOUNT_GRID, Assumptions, Experiment, InfeasibleAssumption, Measured, ab_sample_size,
                       best_discount, break_even_lift, check_feasible, conversion_at, duration_weeks,
                       max_feasible_lift, plan_test, revenue_per_user, revenue_sample_size, sensitivity_grid,
                       sigma_from_anchor, simulate, switch_points, value_factor, win_frequency)

M = Measured(c0=0.2, v0=50.0, a=0.66, installs=20000, payers=4000, v0_se=0.5)


# ---------------------------------------------------------------- exact formulas, validated independently
@pytest.mark.parametrize("d,a,k", [(0.2, 0.6, 0.3), (0.5, 1.0, 0.0), (0.1, 0.0, 1.0), (0.0, 0.5, 0.5)])
def test_value_factor_by_hand(d, a, k):
    discounted = a * (1 - d)                 # revenue during the discount, at the discounted price
    later = (1 - a) * max(0.0, 1 - k * d)    # full-price revenue afterwards, reduced by step-up churn
    assert float(value_factor(d, a, k)) == pytest.approx(discounted + later)


def test_break_even_by_hand():
    # V0 = 100, a = 0.5, d = 0.2, k = 0.3: Vd = 100*(0.8*0.5 + 0.5*0.94) = 87 ; L* = (100/87 - 1)/0.85
    assert float(break_even_lift(0.2, 0.5, 0.85, 0.3)) == pytest.approx((100 / 87 - 1) / 0.85)


def test_break_even_edge_cases():
    assert float(break_even_lift(0.0, 0.7, 0.85, 0.3)) == 0                      # no discount, nothing to recover
    assert float(break_even_lift(0.3, 1.0, 1.0, 0.0)) == pytest.approx(1 / 0.7 - 1)  # permanent cut, rho = 1
    assert float(break_even_lift(0.3, 0.0, 1.0, 0.0)) == 0                       # discount touches nothing
    assert float(break_even_lift(0.3, 0.6, 0.5, 0.3)) == pytest.approx(2 * float(break_even_lift(0.3, 0.6, 1.0, 0.3)))


@given(st.floats(0.02, 0.6), st.floats(0.05, 0.6), st.floats(0.02, 1.0), st.floats(0.3, 1.0), st.floats(0, 1),
       st.floats(0, 0.5))
def test_revenue_at_break_even_equals_full_price(c0, d, a, rho, k, fee):
    L = float(break_even_lift(d, a, rho, k))
    vd = 50 * float(value_factor(d, a, k))
    r = (c0 * vd + c0 * L * rho * vd) * (1 - fee)
    assert r == pytest.approx(c0 * 50 * (1 - fee))


@given(st.floats(0.01, 0.55), st.floats(0.05, 1.0), st.floats(0.3, 1.0), st.floats(0, 1))
def test_break_even_monotone(d, a, rho, k):
    assert break_even_lift(d + 0.05, a, rho, k) > break_even_lift(d, a, rho, k)
    assert break_even_lift(d, a, rho, k) >= break_even_lift(d, a, 1.0, k) - 1e-12


def test_store_fee_applied_to_both_sides():
    for fee in (0.0, 0.15, 0.30):
        s = simulate(M, Assumptions(store_fee=fee, include_sampling=False))
        assert s.attrs["baseline_rev"] == pytest.approx(M.c0 * M.v0 * (1 - fee))
        assert s.loc[0, "rev_mean"] == pytest.approx(s.attrs["baseline_rev"])
    a = simulate(M, Assumptions(store_fee=0.0, include_sampling=False))
    b = simulate(M, Assumptions(store_fee=0.3, include_sampling=False))
    assert np.allclose(a.uplift_vs_base, b.uplift_vs_base) and np.allclose(a.breakeven_lift, b.breakeven_lift)


# ---------------------------------------------------------------- response curve
def test_max_feasible_lift():
    assert float(max_feasible_lift(0.2, 2.0)) == pytest.approx(1.0)
    assert float(max_feasible_lift(0.6, 2.0)) == pytest.approx(1 / 0.6 - 1)  # capped by 100% conversion
    assert float(max_feasible_lift(0.1, 3.0)) == pytest.approx(2.0)


@pytest.mark.parametrize("c0,lift,q", [(0.2, 1.0, 2.0), (0.2, 1.2, 2.0), (0.6, 0.7, 2.0), (0.2, 0.3, 1.0),
                                       (0.2, -0.1, 2.0)])
def test_infeasible_lifts_raise_not_clip(c0, lift, q):
    with pytest.raises(InfeasibleAssumption):
        sigma_from_anchor(c0, lift, q)


def test_simulate_rejects_infeasible_range():
    with pytest.raises(InfeasibleAssumption, match="impossible"):
        simulate(M, Assumptions(lift_low=0.1, lift_mode=0.5, lift_high=1.2, q=2.0))


@pytest.mark.parametrize("low,mode,high", [(0.3, 0.31, 0.3), (0.5, 0.2, 0.6)])
def test_invalid_triangle_rejected(low, mode, high):
    with pytest.raises(InfeasibleAssumption):
        simulate(M, Assumptions(lift_low=low, lift_mode=mode, lift_high=high))


@given(st.floats(0.02, 0.6), st.floats(0.01, 0.99), st.floats(1.2, 5.0))
def test_anchor_reproduced_exactly(c0, frac, q):
    lift = frac * float(max_feasible_lift(c0, q))
    assume(lift > 1e-3)
    sigma = sigma_from_anchor(c0, lift, q)
    assert float(conversion_at(0.2, c0, sigma, q)) / c0 - 1 == pytest.approx(lift, rel=1e-6)


@given(st.floats(0.02, 0.6), st.floats(0.01, 0.99), st.floats(1.2, 5.0))
def test_curve_bounded_increasing_pinned(c0, frac, q):
    sigma = sigma_from_anchor(c0, frac * float(max_feasible_lift(c0, q)), q)
    c = conversion_at(DISCOUNT_GRID, c0, sigma, q)
    assert c[0] == pytest.approx(c0, rel=1e-9)
    assert np.all(np.diff(c) >= -1e-12)
    assert np.all(c <= min(1.0, q * c0) + 1e-12)


def test_zero_lift_means_no_response():
    sigma = sigma_from_anchor(0.2, 0.0, 2.0)
    assert np.isinf(sigma)
    assert np.allclose(conversion_at(DISCOUNT_GRID, 0.2, sigma, 2.0), 0.2)
    assert best_discount(0.2, 50, 0.66, 0.0, Assumptions()) == 0.0


# ---------------------------------------------------------------- simulation
def test_simulation_reproducible_and_ordered():
    a = simulate(M, Assumptions())
    pd.testing.assert_frame_equal(a, simulate(M, Assumptions()))
    assert (a.rev_p05 <= a.rev_mean + 1e-9).all() and (a.rev_mean <= a.rev_p95 + 1e-9).all()


def test_interval_label_states_what_is_included():
    assert "only" in simulate(M, Assumptions(include_sampling=False)).attrs["interval_label"]
    assert "sampling" in simulate(M, Assumptions(include_sampling=True)).attrs["interval_label"]


def test_sampling_uncertainty_widens_interval():
    narrow = simulate(M, Assumptions(lift_low=0.2, lift_mode=0.2, lift_high=0.2, include_sampling=False))
    wide = simulate(M, Assumptions(lift_low=0.2, lift_mode=0.2, lift_high=0.2, include_sampling=True))
    assert (narrow.rev_p95 - narrow.rev_p05).max() < 1e-9          # point assumption, no sampling -> no band
    assert (wide.rev_p95 - wide.rev_p05).iloc[1:].min() > 0


@pytest.mark.parametrize("low,mode,high", [(0.2, 0.2, 0.2), (0.0, 0.0, 0.0), (0.0, 0.0, 0.5), (0.5, 0.5, 0.5)])
def test_degenerate_but_valid_ranges(low, mode, high):
    s = simulate(M, Assumptions(lift_low=low, lift_mode=mode, lift_high=high))
    assert s.rev_mean.notna().all()


def test_p_beats_is_zero_without_response():
    s = simulate(M, Assumptions(lift_low=0, lift_mode=0, lift_high=0, include_sampling=False))
    assert (s.p_beats_base.dropna() == 0).all()


# ---------------------------------------------------------------- sensitivity
@settings(max_examples=150, deadline=None)
@given(st.floats(0.02, 0.6), st.floats(0.05, 1.0), st.floats(0.0, 0.98), st.floats(1.2, 5.0), st.floats(0.3, 1.0),
       st.floats(0.0, 1.0))
def test_best_discount_agrees_with_break_even(c0, a, frac, q, rho, k):
    lift = frac * float(max_feasible_lift(c0, q))
    asm = Assumptions(q=q, rho=rho, k=k)
    sigma = sigma_from_anchor(c0, lift, q)
    d = DISCOUNT_GRID[1:]
    margin = conversion_at(d, c0, sigma, q) / c0 - 1 - break_even_lift(d, a, rho, k)
    best = best_discount(c0, 50, a, lift, asm)
    if margin.max() > 1e-6:
        assert best > 0 and margin[list(d).index(best)] > 0
    elif margin.max() < -1e-6:
        assert best == 0


def test_best_discount_nan_when_infeasible():
    assert np.isnan(best_discount(0.2, 50, 0.66, 1.2, Assumptions(q=2.0)))


def test_sensitivity_grid_marks_infeasible_cells():
    g = sensitivity_grid(0.2, 50, 0.66, Assumptions(), "q")
    assert g[(g.q == 1.25) & (g.lift_at_20 >= 0.25)].best_discount.isna().all()
    assert g[(g.q == 5.0)].best_discount.notna().all()
    assert 2.0 in set(g.q)  # current value included


def test_switch_points_cover_feasible_range():
    sp = switch_points(0.2, 50, 0.66, Assumptions(q=2.0))
    assert sp.lift_from.iloc[0] == 0 and sp.best_discount.iloc[0] == 0
    assert sp.lift_to.iloc[-1] < 1.0  # max feasible lift at q = 2
    assert np.allclose(sp.lift_from.iloc[1:].values, sp.lift_to.iloc[:-1].values + 0.01)


def test_saturation_lowers_best_discount():
    asm = Assumptions(q=2.0)
    assert 0 < best_discount(0.2, 50, 0.66, 0.95, asm) < best_discount(0.2, 50, 0.66, 0.4, asm)


def test_win_frequency_sums_to_one():
    f = win_frequency(0.2, 50, 0.66, Assumptions())
    assert f.sum() == pytest.approx(1.0)


# ---------------------------------------------------------------- sample size and duration
def test_textbook_sample_size():
    assert ab_sample_size(0.10, 0.2) == 3841  # 10% -> 12%, alpha 0.05 two-sided, power 0.8


def test_sample_size_has_80pct_power():
    rng = np.random.default_rng(0)
    for c0, lift in [(0.2, 0.2), (0.112, 0.15), (0.48, 0.05)]:
        n = ab_sample_size(c0, lift)
        x1, x2 = rng.binomial(n, c0, 20000), rng.binomial(n, c0 * (1 + lift), 20000)
        pb = (x1 + x2) / (2 * n)
        z = (x2 - x1) / n / np.sqrt(pb * (1 - pb) * 2 / n)
        assert 0.78 < np.mean(np.abs(z) > 1.96) < 0.82


def test_bonferroni_increases_sample_size():
    assert ab_sample_size(0.1, 0.2, comparisons=3) > ab_sample_size(0.1, 0.2, comparisons=2) > ab_sample_size(0.1, 0.2)


def test_sample_size_edge_cases():
    assert ab_sample_size(0.2, 0) == 0
    assert ab_sample_size(0.6, 1.0) == 0      # target conversion >= 100% is impossible
    assert ab_sample_size(0.2, 0.1) > ab_sample_size(0.2, 0.2)


def test_revenue_sample_size():
    assert revenue_sample_size(1.0, 0.1) == 1570
    assert revenue_sample_size(1.0, 0.0) == 0


def test_duration():
    # 1,000 per arm, 1,000 eligible/week, 50% allocation, 1 discount arm -> 250 per group per week -> 4 weeks + 2 weeks wait
    assert duration_weeks(1000, 1000, 0.5, 1, 14) == pytest.approx(6.0)
    assert duration_weeks(1000, 1000, 1.0, 3, 0) == pytest.approx(4.0)
    assert duration_weeks(1000, 0, 1.0, 1, 14) == float("inf")


# ---------------------------------------------------------------- plan
def _sim(**kw):
    return simulate(M, Assumptions(**kw))


def test_plan_worth_testing_and_rule():
    p = plan_test(_sim(lift_mode=0.5, lift_high=0.9), 0.2, Experiment(weekly_eligible=1e7))
    assert p.test_discount > 0 and set(p.table.verdict) <= {"Worth testing", "Not plausible", "Too slow to test"}
    assert "not a proven optimum" in p.headline
    for must in ["users per arm", "Primary metric", "Guardrails", "Randomisation", "Renewal review", "Roll out only if"]:
        assert must in p.decision_rule


def test_plan_too_slow():
    p = plan_test(_sim(lift_mode=0.5, lift_high=0.9), 0.2, Experiment(weekly_eligible=10))
    assert p.test_discount == 0 and "Keep full price" in p.headline
    assert (p.table[p.table.p_beats_base >= 0.5].verdict == "Too slow to test").all()


def test_plan_not_plausible():
    p = plan_test(_sim(lift_low=0, lift_mode=0, lift_high=0.02), 0.2, Experiment(weekly_eligible=1e7))
    assert p.test_discount == 0 and (p.table.verdict == "Not plausible").all()


@pytest.mark.parametrize("m", [0.05, 0.15, 0.3])
def test_max_discount_respected(m):
    p = plan_test(_sim(lift_mode=0.6, lift_high=0.95), 0.2, Experiment(weekly_eligible=1e7, max_discount=m))
    assert p.table.discount.max() <= m + 1e-9 and p.test_discount <= m + 1e-9


def test_chosen_arm_beats_full_price_in_expectation():
    p = plan_test(_sim(lift_mode=0.4, lift_high=0.8), 0.2, Experiment(weekly_eligible=1e7, max_discount=0.5))
    row = p.table[p.table.discount == p.test_discount].iloc[0]
    assert row.uplift_vs_base > 0 and row.p_beats_base >= 0.5 and row.verdict == "Worth testing"


def test_more_arms_slow_the_test():
    s = _sim(lift_mode=0.5, lift_high=0.9)
    one = plan_test(s, 0.2, Experiment(weekly_eligible=5000, arms=1)).table.set_index("discount").weeks
    three = plan_test(s, 0.2, Experiment(weekly_eligible=5000, arms=3)).table.set_index("discount").weeks
    assert (three > one).all()


# ---------------------------------------------------------------- variable cost
from economics import margin_factor, payments_factor  # noqa: E402


def test_zero_cost_reproduces_revenue_formula():
    for d, a, k, fee in [(0.2, 0.6, 0.3, 0.15), (0.4, 1.0, 0.0, 0.3), (0.1, 0.3, 1.0, 0.0)]:
        assert float(break_even_lift(d, a, 0.85, k, fee, 0.0)) == pytest.approx((1 / float(value_factor(d, a, k)) - 1) / 0.85)


def test_cost_break_even_by_hand():
    # V0 = 100, a = 0.5, d = 0.2, k = 0.3, fee = 0.15, g = 0.2
    # revenue kept 0.87, payments kept 0.5 + 0.5*0.94 = 0.97 ; m_d = 0.85*0.87 - 0.2*0.97 = 0.5455 ; m_0 = 0.65
    assert float(payments_factor(0.2, 0.5, 0.3)) == pytest.approx(0.97)
    assert float(margin_factor(0.2, 0.5, 0.3, 0.15, 0.2)) == pytest.approx(0.5455)
    assert float(break_even_lift(0.2, 0.5, 0.85, 0.3, 0.15, 0.2)) == pytest.approx((0.65 / 0.5455 - 1) / 0.85)


def test_cost_raises_break_even():
    for d in (0.1, 0.3, 0.5):
        assert break_even_lift(d, 0.6, 0.85, 0.3, 0.15, 0.2) > break_even_lift(d, 0.6, 0.85, 0.3, 0.15, 0.0)


def test_discount_that_never_pays_is_infinite():
    # permanent 50% cut with costs at 45% of list price: discounted margin is negative
    assert np.isinf(float(break_even_lift(0.5, 1.0, 1.0, 0.0, 0.15, 0.45)))


@given(st.floats(0.02, 0.6), st.floats(0.05, 0.5), st.floats(0.02, 1.0), st.floats(0.3, 1.0), st.floats(0, 1),
       st.floats(0, 0.3), st.floats(0, 0.3))
def test_contribution_at_break_even_equals_full_price(c0, d, a, rho, k, fee, g):
    L = float(break_even_lift(d, a, rho, k, fee, g))
    assume(np.isfinite(L))
    md = 50 * float(margin_factor(d, a, k, fee, g))
    assert c0 * md + c0 * L * rho * md == pytest.approx(c0 * 50 * float(margin_factor(0, a, k, fee, g)))


def test_simulation_with_cost_is_consistent():
    s = simulate(M, Assumptions(cost=0.2, include_sampling=False))
    assert s.attrs["baseline_rev"] == pytest.approx(M.c0 * M.v0 * (1 - 0.15 - 0.2))
    assert s.loc[0, "rev_mean"] == pytest.approx(s.attrs["baseline_rev"])
    no_cost = simulate(M, Assumptions(cost=0.0, include_sampling=False))
    assert (s.breakeven_lift.iloc[1:] > no_cost.breakeven_lift.iloc[1:]).all()


def test_cost_must_leave_a_margin():
    with pytest.raises(InfeasibleAssumption):
        simulate(M, Assumptions(cost=0.9, store_fee=0.15))
