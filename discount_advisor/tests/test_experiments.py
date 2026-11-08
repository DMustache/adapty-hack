"""The randomized A/B tests in the data: arms, statistics, balance, blend detection."""
import numpy as np
import pytest

import experiments as ex


@pytest.fixture(scope="module")
def arms(ds):
    return ex.arm_results(ds, 12)


def test_every_test_has_its_control_and_one_variant(arms, ds):
    tests = set(ds.users.ab_test.dropna())
    assert set(arms.test) == tests == set(ex.CONTROL_ARM)
    for test, g in arms.groupby("test"):
        assert (g.role == "control").sum() == 1 and (g.role == "variant").sum() == 1
        assert g[g.role == "control"].arm.iloc[0] == ex.CONTROL_ARM[test]


def test_arms_partition_each_test(arms, ds):
    u = ds.users
    for test, g in arms.groupby("test"):
        assert g.installs.sum() == (u.mature & (u.ab_test == test)).sum()
        assert g.payers.sum() == (u.mature & u.converted & (u.ab_test == test)).sum()


def test_conversion_by_hand(arms, ds):
    u = ds.users[ds.users.mature]
    row = arms[(arms.arm == "onb_weekly")].iloc[0]
    m = (u.ab_test == row.test) & (u.flow == "onb_weekly")
    assert row.conversion == pytest.approx(u[m].converted.mean())


def test_lifts_consistent(arms):
    for test, g in arms.groupby("test"):
        c, v = g[g.role == "control"].iloc[0], g[g.role == "variant"].iloc[0]
        assert v.conv_lift == pytest.approx(v.conversion / c.conversion - 1)
        assert v.conv_diff == pytest.approx(v.conversion - c.conversion)
        assert v.revenue_lift == pytest.approx(v.revenue_per_install / c.revenue_per_install - 1)
        assert c.conv_lift == 0 and np.isnan(c.p_value)


def test_randomization_is_balanced(arms):
    assert ex.max_imbalance(arms) < 0.05


def test_two_prop_test_by_hand():
    diff, half, p = ex.two_prop_test(100, 1000, 130, 1000)
    assert diff == pytest.approx(0.03)
    assert half == pytest.approx(1.96 * np.sqrt(0.1 * 0.9 / 1000 + 0.13 * 0.87 / 1000))
    pool = 0.115
    z = 0.03 / np.sqrt(pool * (1 - pool) * 2 / 1000)
    from scipy.stats import norm
    assert p == pytest.approx(2 * norm.sf(z))
    assert ex.two_prop_test(130, 1000, 100, 1000)[2] == pytest.approx(p)  # symmetric
    assert ex.two_prop_test(0, 10, 0, 10)[2] == 1.0


def test_all_three_effects_are_significant(arms):
    assert (arms[arms.role == "variant"].p_value < 0.001).all()


def test_mixed_flow_detection(ds):
    u = ds.users
    onb = ex.mixed_flows(ds, u.placement == "onboarding")
    assert set(onb.index) == {"onb_trial", "onb_weekly"} and onb.sum() == pytest.approx(1)
    assert len(ex.mixed_flows(ds, u.placement == "ai_limit_reached")) == 1
    assert len(ex.mixed_flows(ds, (u.placement == "onboarding") & (u.flow == "onb_weekly"))) == 1
