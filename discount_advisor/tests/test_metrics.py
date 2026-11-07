"""Independent re-computation of every measured number."""
import numpy as np
import pandas as pd
import pytest

from data import CONVERSION_WINDOW_DAYS
from metrics import (MIN_AT_RISK, SEGMENT_DIMENSIONS, periods_in_horizon, refund_rate, renewal_survival,
                     segment_baseline, segment_table, wilson_ci)


def _all(ds):
    return pd.Series(True, index=ds.users.index)


# ---------------------------------------------------------------- conversion
def test_conversion_recomputed_from_raw(ds, raw):
    u, t = raw
    inst = pd.to_datetime(u.install_at, utc=True)
    paid = t[t.price_usd > 0].copy()
    paid["purchased_at"] = pd.to_datetime(paid.purchased_at, utc=True)
    first = paid.sort_values("seq").groupby("user_id").purchased_at.first()
    lag = (pd.Series(first.reindex(u.user_id).to_numpy(), index=u.index) - inst).dt.total_seconds() / 86400
    mature = inst <= ds.as_of - pd.Timedelta(days=CONVERSION_WINDOW_DAYS)
    expected = lag[mature].le(CONVERSION_WINDOW_DAYS).mean()
    assert segment_baseline(ds, _all(ds), "all", 12).conversion == pytest.approx(expected, abs=1e-12)


def test_denominators_match_audience(ds, survivals):
    m = ds.users.placement == "main"
    b = segment_baseline(ds, m, "main", 12, survivals)
    assert b.installs == (m & ds.users.mature).sum()
    assert b.converters == (m & ds.users.mature & ds.users.converted).sum()
    weeks = (ds.as_of - ds.users.install_at.min()).total_seconds() / (7 * 86400)
    assert b.weekly_installs == pytest.approx(m.sum() / weeks)


def test_wilson_ci():
    lo, hi = wilson_ci(200, 1000)
    assert lo < 0.2 < hi and hi - lo == pytest.approx(0.0496, abs=0.002)
    assert wilson_ci(0, 0) == (0.0, 0.0)
    lo, hi = wilson_ci(0, 50)
    assert lo == 0 and 0 < hi < 0.1
    lo, hi = wilson_ci(50, 50)
    assert hi == 1 and lo > 0.9


# ---------------------------------------------------------------- horizon and survival
@pytest.mark.parametrize("product,h,n", [("weekly", 12, 53), ("weekly", 3, 14), ("monthly", 12, 13),
                                         ("monthly", 3, 4), ("annual", 12, 1), ("annual", 3, 1),
                                         ("pro_annual", 12, 1), ("lifetime", 12, 1)])
def test_payments_in_horizon(product, h, n):
    assert periods_in_horizon(product, h) == n


@pytest.mark.parametrize("product", ["weekly", "monthly", "annual", "annual_trial", "pro_annual"])
@pytest.mark.parametrize("h", [3, 6, 12])
def test_survival_shape(ds, product, h):
    sv = renewal_survival(ds.chains, product, h)
    s = sv.s
    assert len(s) == periods_in_horizon(product, h)
    assert s[0] == 1.0 and np.all(np.diff(s) <= 1e-12) and np.all((s >= 0) & (s <= 1))
    assert 1 <= sv.observed_periods <= len(s)


def test_km_equals_naive_without_censoring():
    chains = pd.DataFrame({"product": "monthly", "paid_periods": [1] * 40 + [2] * 30 + [3] * 30, "censored": False})
    assert np.allclose(renewal_survival(chains, "monthly", 2).s, [1.0, 0.6, 0.3])  # 2 months = 3 payments


def test_km_excludes_censored_from_risk_set():
    # 10 ended after receipt 1, 40 still in receipt 1 at cutoff (censored), 50 reached receipt 2
    chains = pd.DataFrame({"product": "monthly", "paid_periods": [1] * 50 + [2] * 50,
                           "censored": [False] * 10 + [True] * 40 + [False] * 50})
    assert renewal_survival(chains, "monthly", 2).s[1] == pytest.approx(50 / 60)


def test_km_all_censored_is_not_identified():
    chains = pd.DataFrame({"product": "monthly", "paid_periods": [1] * 100, "censored": True})
    sv = renewal_survival(chains, "monthly", 3)
    assert sv.observed_periods == 1 and not sv.tail_identified


def test_km_tail_rule():
    # constant 50% retention for 3 observed steps then data runs out -> tail = 0.5
    pp = [1] * 400 + [2] * 200 + [3] * 100 + [4] * 100
    cens = [False] * 700 + [True] * 100
    chains = pd.DataFrame({"product": "monthly", "paid_periods": pp, "censored": cens})
    sv = renewal_survival(chains, "monthly", 6)  # 7 payments
    assert sv.observed_periods == 4 and sv.extrapolated   # steps 1->2, 2->3, 3->4 observed; 4->5 all censored
    assert sv.tail_retention == pytest.approx(0.5)
    assert sv.s[4] == pytest.approx(sv.s[3] * 0.5) and sv.s[6] == pytest.approx(0.5 ** 6)


def test_km_first_weekly_renewal_by_hand(ds):
    c = ds.chains[ds.chains["product"] == "weekly"]
    at_risk = len(c) - ((c.paid_periods == 1) & c.censored).sum()
    assert at_risk >= MIN_AT_RISK
    assert renewal_survival(ds.chains, "weekly", 12).s[1] == pytest.approx((c.paid_periods >= 2).sum() / at_risk)


def test_lifetime_excluded_from_renewal_metrics(ds):
    sv = renewal_survival(ds.chains, "lifetime", 12)
    assert sv.s.tolist() == [1.0]


# ---------------------------------------------------------------- revenue
def test_refund_rate_by_hand(ds, raw):
    _, t = raw
    paid = t[t.price_usd > 0]
    expected = paid.refunded_at.notna().groupby(paid["product"]).mean()
    assert np.allclose(refund_rate(ds.tx).sort_index(), expected.sort_index())


def test_value_per_payer_brute_force(ds, survivals):
    m = ds.users.country == "DE"
    b = segment_baseline(ds, m, "DE", 12, survivals)
    rr = refund_rate(ds.tx)
    u = ds.users[m & ds.users.mature & ds.users.converted]
    vals = [r.first_price_usd * survivals[r.product].s.sum() * (1 - rr[r.product]) for r in u.itertuples()]
    assert b.value_per_converter == pytest.approx(np.mean(vals))


def test_revenue_split_sums_to_one(ds, survivals):
    for pl in ds.users.placement.unique():
        b = segment_baseline(ds, ds.users.placement == pl, pl, 12, survivals)
        assert sum(b.v0_split.values()) == pytest.approx(1.0)
        assert all(v >= -1e-12 for v in b.v0_split.values())


def test_no_extrapolation_for_annual_only_audience(ds, survivals):
    b = segment_baseline(ds, ds.users.placement == "ai_limit_reached", "ai", 12, survivals)
    if set(b.product_mix.index) <= {"annual", "annual_trial", "pro_annual", "lifetime"}:
        assert b.v0_split["extrapolated_tail"] == pytest.approx(0)
        assert b.affected_share("first_payment") == pytest.approx(1.0)


def test_observed_receipts_reported_separately(ds, survivals):
    b = segment_baseline(ds, _all(ds), "all", 12, survivals)
    u = ds.users[ds.users.mature & ds.users.converted]
    assert b.observed_net_per_payer == pytest.approx(u.observed_net_usd.mean())


def test_affected_share_ordering_and_bounds(ds, survivals):
    b = segment_baseline(ds, _all(ds), "all", 12, survivals)
    shares = [b.affected_share(d) for d in ["first_payment", "1m", "3m", "all"]]
    assert all(0 < x <= y + 1e-12 for x, y in zip(shares, shares[1:]))
    assert shares[-1] == pytest.approx(1.0)
    with pytest.raises(ValueError):
        b.affected_share("forever")


def test_affected_share_depends_on_audience_mix(ds, survivals):
    weeklyish = segment_baseline(ds, ds.users.placement == "main", "m", 12, survivals).affected_share("first_payment")
    annualish = segment_baseline(ds, ds.users.placement == "ai_limit_reached", "a", 12, survivals).affected_share("first_payment")
    assert weeklyish < annualish


def test_affected_share_depends_on_horizon(ds):
    m = ds.users.placement == "main"
    short = segment_baseline(ds, m, "m", 3).affected_share("first_payment")
    long = segment_baseline(ds, m, "m", 12).affected_share("first_payment")
    assert long < short  # more renewals in a longer horizon -> first payment is a smaller share


def test_revenue_sd_consistent(ds, survivals):
    b = segment_baseline(ds, _all(ds), "all", 12, survivals)
    assert b.revenue_per_install == pytest.approx(b.conversion * b.value_per_converter)
    assert b.revenue_sd > b.revenue_per_install and b.v0_se > 0


# ---------------------------------------------------------------- segments
@pytest.mark.parametrize("dim", list(SEGMENT_DIMENSIONS))
def test_segments_partition_the_population(ds, dim):
    tbl = segment_table(ds, dim, 12)
    assert tbl.installs.sum() == ds.users.mature.sum()
    assert tbl.payers.sum() == (ds.users.mature & ds.users.converted).sum()


def test_segments_within_placement_partition_it(ds):
    pl = ds.users.placement == "onboarding"
    tbl = segment_table(ds, "Country", 12, within=pl)
    assert tbl.installs.sum() == (pl & ds.users.mature).sum()
    assert tbl.weekly_installs.sum() == pytest.approx(segment_baseline(ds, pl, "o", 12).weekly_installs)


def test_small_cohort_flag(ds, survivals):
    m = (ds.users.country == "SE") & (ds.users.placement == "win_back")
    b = segment_baseline(ds, m, "tiny", 12, survivals)
    assert b.small and b.payers < 30


def test_empty_segment_does_not_crash(ds, survivals):
    b = segment_baseline(ds, ds.users.country == "XX", "none", 12, survivals)
    assert b.installs == 0 and b.conversion == 0 and b.value_per_converter == 0 and b.small
