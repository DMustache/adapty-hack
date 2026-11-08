"""End-to-end: drive the Streamlit app through many settings; it must never crash and must always say something."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parent.parent / "app.py")
PLACEMENT = "Paywall placement (where the offer is shown)"


@pytest.fixture(scope="module")
def at():
    a = AppTest.from_file(APP, default_timeout=300).run()
    assert not a.exception
    return a


def w(collection, label):
    for x in collection:
        if x.label == label:
            return x
    raise KeyError(label)


def texts(at):
    return [x.value for x in list(at.success) + list(at.info) + list(at.error) + list(at.warning)]


def check(at, ctx):
    assert not at.exception, (ctx, [e.value for e in at.exception])
    t = texts(at)
    blocked = any(s.startswith("Only ") or "can't be used" in s for s in t)
    if not blocked:
        assert any("Worth testing:" in s or "Keep full price" in s for s in t), ctx
    return blocked


def reset(at):
    w(at.sidebar.selectbox, PLACEMENT).set_value("onboarding")
    w(at.sidebar.selectbox, "Segment filter").set_value("None")
    at.run()


def test_labels_and_synthetic_notice(at):
    md = " ".join(m.value for m in at.markdown) + " ".join(c.value for c in at.caption)
    for tag in ["DATA", "CALCULATED", "ASSUMED"]:
        assert tag in md
    assert "Synthetic" in md or "synthetic" in md
    assert [t.label for t in at.tabs] == ["Recommendation", "Sensitivity", "Compare segments", "Randomized tests",
                                         "Baselines", "Data reality check", "Live Adapty", "Method"]


def test_every_placement(at, ds):
    for p in sorted(ds.users.placement.unique()) + ["All placements (pooled)"]:
        w(at.sidebar.selectbox, PLACEMENT).set_value(p).run()
        assert not check(at, p), p  # every placement has enough payers
    reset(at)


@pytest.mark.parametrize("dim,col", [("Country", "country"), ("Price tier", "price_tier"), ("Platform", "platform"),
                                     ("Acquisition channel", "acquisition_channel"), ("Flow (paywall)", "flow")])
def test_segments_within_onboarding(at, ds, dim, col):
    w(at.sidebar.selectbox, "Segment filter").set_value(dim).run()
    for v in sorted(ds.users.loc[ds.users.placement == "onboarding", col].astype(str).unique()):
        w(at.sidebar.selectbox, dim).set_value(v).run()
        check(at, (dim, v))
    reset(at)


def test_small_cohort_blocked_cleanly(at):
    w(at.sidebar.selectbox, PLACEMENT).set_value("win_back").run()
    w(at.sidebar.selectbox, "Segment filter").set_value("Country").run()
    w(at.sidebar.selectbox, "Country").set_value("SE").run()
    assert check(at, "SE x win_back")
    assert any("payers" in s and "minimum" in s for s in texts(at))
    reset(at)


@pytest.mark.parametrize("duration", ["First paid payment only", "First month of payments",
                                      "First 3 months of payments", "Every payment (permanent price cut)"])
@pytest.mark.parametrize("horizon", [3, 6, 12])
def test_offer_and_horizon(at, duration, horizon):
    w(at.sidebar.radio, "Discount applies to").set_value(duration)
    w(at.sidebar.select_slider, "Revenue horizon (months)").set_value(horizon)
    at.run()
    check(at, (duration, horizon))
    assert any("12-month horizon" in s for s in texts(at)) == (horizon == 12)


def test_infeasible_assumption_is_flagged_not_clipped(at):
    w(at.sidebar.slider, "Low – high").set_value((0.05, 1.3)).run()
    assert not at.exception
    assert any("impossible" in s for s in texts(at))
    w(at.sidebar.slider, "Market ceiling q (max conversion = min(1, q × baseline))").set_value(3.0).run()
    assert not any("impossible" in s for s in texts(at))
    check(at, "after raising ceiling")
    w(at.sidebar.slider, "Market ceiling q (max conversion = min(1, q × baseline))").set_value(2.0)
    w(at.sidebar.slider, "Low – high").set_value((0.05, 0.5)).run()


@pytest.mark.parametrize("rng", [(0.0, 0.0), (0.3, 0.3), (0.0, 0.9)])
def test_degenerate_lift_ranges(at, rng):
    w(at.sidebar.slider, "Low – high").set_value(rng).run()
    check(at, rng)
    w(at.sidebar.slider, "Low – high").set_value((0.05, 0.5)).run()


@pytest.mark.parametrize("label,value", [
    ("ρ: value of a discount-driven buyer vs a regular one", 0.3),
    ("ρ: value of a discount-driven buyer vs a regular one", 1.0),
    ("k: step-up churn when full price returns", 0.0),
    ("k: step-up churn when full price returns", 1.0),
    ("Max allowed discount", 0.05),
    ("Max allowed discount", 0.5),
    ("Worth testing only if it beats full price in ≥ this share of scenarios", 0.9),
    ("Longest acceptable test (weeks)", 2),
    ("Share of eligible traffic in the test", 0.1),
    ("Variable cost per paid period (% of list price)", 0.3),
    ("Variable cost per paid period (% of list price)", 0.0),
])
def test_slider_extremes(at, label, value):
    w(at.sidebar.slider, label).set_value(value).run()
    check(at, (label, value))


def test_arms_fee_sampling_and_traffic(at):
    for arms in (2, 3, 1):
        w(at.sidebar.select_slider, "Discount arms (plus one control)").set_value(arms).run()
        check(at, arms)
    w(at.sidebar.selectbox, "Store fee (applied to baseline and discount alike)").set_value(0.30).run()
    check(at, "fee")
    w(at.sidebar.checkbox, "Include sampling uncertainty of measured c₀ and V₀").uncheck().run()
    check(at, "no sampling")
    w(at.sidebar.checkbox, "Use my real weekly traffic instead of the dataset sample").check().run()
    for n in (10_000_000, 100):
        w(at.sidebar.number_input, "Real eligible users per week").set_value(n).run()
        check(at, n)
    w(at.sidebar.checkbox, "Use my real weekly traffic instead of the dataset sample").uncheck().run()


def test_main_area_selectors(at):
    for p in ["q", "rho", "k"]:
        w(at.selectbox, "Second assumption").set_value(p).run()
        check(at, p)
    for d in ["Placement", "Country", "Price tier", "Platform", "Acquisition channel", "Flow (paywall)"]:
        w(at.selectbox, "Compare across").set_value(d).run()
        check(at, d)
        w(at.selectbox, "Break down by").set_value(d).run()
        check(at, d)


def test_live_tab_renders_from_snapshots(at):
    """The Live Adapty tab must render without network access, with or without snapshots."""
    assert not at.exception
    texts_all = " ".join(m.value for m in at.markdown) + " ".join(c.value for c in at.caption)
    assert "local snapshots" in texts_all


def test_blend_warning_and_flow_filter(at):
    """onboarding mixes two A/B-test paywalls: warn, and the warning goes away when one paywall is selected."""
    reset(at)
    assert any("different paywalls" in x.value for x in at.warning)
    w(at.sidebar.selectbox, "Segment filter").set_value("Flow (paywall)").run()
    w(at.sidebar.selectbox, "Flow (paywall)").set_value("onb_weekly").run()
    check(at, "onb_weekly")
    assert not any("different paywalls" in x.value for x in at.warning)
    reset(at)


def test_randomized_tests_tab(at):
    heads = [s.value for s in at.subheader]
    for t in ["Onboarding: annual trial vs weekly first", "Main: 3 plans vs lifetime anchor (NA)",
              "Settings: upgrade vs lifetime anchor"]:
        assert t in heads
