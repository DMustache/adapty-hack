"""Live verification: every seeded profile in the Adapty app vs the offline dataset the Discount Advisor uses.

Skipped unless ADAPTY_LIVE=1. Uses the cached snapshot in .live_cache/ (all 6,000 profiles); set
ADAPTY_LIVE_REFRESH=1 to re-download first (~2 min, read-only). Run:
    ADAPTY_LIVE=1 python -m pytest tests/test_live_adapty.py -q
"""
import json
import os

import numpy as np
import pandas as pd
import pytest

pytestmark = pytest.mark.skipif(os.environ.get("ADAPTY_LIVE") != "1", reason="live Adapty test; set ADAPTY_LIVE=1")

from adapty_live import LIVE_EVERY, N_USERS as N_HIST  # noqa: E402  (ADAPTY_N_USERS / ADAPTY_LIVE_EVERY)
ATTRS = ["acquisition_channel", "onboarding_goal", "ai_edits_first_day", "photos_imported", "push_opt_in", "app_version"]


@pytest.fixture(scope="module")
def snap():
    from adapty_live import snapshot
    return snapshot(refresh=os.environ.get("ADAPTY_LIVE_REFRESH") == "1")


@pytest.fixture(scope="module")
def run_id():
    from adapty_live import RUN_ID
    return RUN_ID


@pytest.fixture(scope="module")
def live(snap, run_id):
    """One row per historical user u00000..u04999 with the live profile's key fields."""
    rows = []
    for i in range(N_HIST):
        p = snap[f"lumen_{run_id}_{i:05d}"]
        subs, ns = p.get("subscriptions") or [], p.get("non_subscriptions") or []
        item = (subs or ns or [{}])[0]
        rows.append({"user_id": f"u{i:05d}", "app_id": p.get("app_id"), "rev": p.get("total_revenue_usd") or 0.0,
                     "n_items": len(subs) + len(ns), "is_sub": bool(subs), "spid": item.get("store_product_id"),
                     "store": item.get("store"), "orig": item.get("originally_purchased_at") or item.get("purchased_at"),
                     "exp": item.get("expires_at"), "reason": item.get("cancellation_reason"),
                     "offer": (item.get("offer") or {}).get("type"),
                     "access": [a.get("access_level_id") for a in p.get("access_levels") or []],
                     "attributes": {a["key"]: a["value"] for a in p.get("custom_attributes") or []}})
    df = pd.DataFrame(rows).set_index("user_id")
    for c in ["orig", "exp"]:
        df[c] = pd.to_datetime(df[c], utc=True)
    return df


@pytest.fixture(scope="module")
def offline(raw):
    u, t = raw
    t = t.copy()
    for c in ["purchased_at", "expires_at", "originally_purchased_at", "refunded_at"]:
        t[c] = pd.to_datetime(t[c], utc=True)
    t["refunded"] = t.refunded_at.notna()
    t = t.sort_values(["user_id", "seq"])
    g = t.groupby("user_id")
    o = pd.DataFrame({
        "product": g["product"].first(), "spid": g["store_product_id"].first(),
        "orig": g["originally_purchased_at"].first().fillna(g["purchased_at"].first()),
        "last_purchase": g["purchased_at"].last(), "last_exp": g["expires_at"].last(),
        "last_refunded": g["refunded"].last(), "reason": g["cancellation_reason"].last(),
        "last_offer": g.tail(1).set_index("user_id")["offer"], "currency": g["currency"].first(),
        "net_local": t.assign(n=t.price_local.where(~t.refunded, 0)).groupby("user_id").n.sum(),
        "gross_local": g["price_local"].sum(),
        "net_usd": t.assign(n=t.price_usd.where(~t.refunded, 0)).groupby("user_id").n.sum(),
    })
    users = u.set_index("user_id")
    return users, o


@pytest.fixture(scope="module")
def shift(live, offline):
    _, o = offline
    m = live.orig.notna()
    return (live.orig[m] - o.orig.reindex(live.index)[m]).dt.total_seconds()


# ------------------------------------------------------------------ completeness
def test_every_seeded_profile_exists(snap, run_id):
    from adapty_live import customer_ids
    ids = customer_ids(run_id)
    assert len(ids) == N_HIST + (N_HIST // LIVE_EVERY if LIVE_EVERY else 0)
    missing = [c for c in ids if snap.get(c) is None]
    assert not missing, f"{len(missing)} profiles missing, e.g. {missing[:5]}"


def test_all_profiles_belong_to_the_app(live, snap):
    from adapty_live import APP_ID
    assert all(p["app_id"] == APP_ID for p in snap.values())


def test_seed_marker_on_every_profile(snap):
    assert all(any(a["key"] == "seed_source" for a in p.get("custom_attributes") or []) for p in snap.values())


# ------------------------------------------------------------------ user attributes
@pytest.mark.parametrize("key", ATTRS)
def test_custom_attributes_match(live, offline, key):
    users, _ = offline
    lv = live["attributes"].map(lambda a: a.get(key))
    ov = users.reindex(live.index)[key]
    same = (lv.astype(str) == ov.astype(str)) | (pd.to_numeric(lv, errors="coerce") == pd.to_numeric(ov, errors="coerce"))
    assert same.all(), f"{(~same).sum()} mismatches for {key}"


def test_store_matches_platform(live, offline):
    users, _ = offline
    payers = live[live.n_items > 0]
    expected = users.reindex(payers.index).platform.map({"iOS": "app_store", "Android": "play_store"})
    assert (payers.store == expected).all()


# ------------------------------------------------------------------ purchases
def test_same_users_are_payers_or_triallers(live, offline):
    _, o = offline
    has_tx = o.reindex(live.index)["product"].notna()
    assert ((live.n_items > 0) == has_tx).all()


def test_store_product_ids_match(live, offline):
    _, o = offline
    m = live.n_items > 0
    assert (live.spid[m] == o.reindex(live.index).spid[m]).all()


def test_lifetime_never_expires_unless_refunded(live, offline, shift):
    """Adapty lists a lifetime purchase as a subscription item with no expiry; a refund sets expiry = purchase time
    and revenue to 0."""
    _, o = offline
    oo = o.reindex(live.index)
    lt = oo["product"] == "lifetime"
    ref = lt & oo.last_refunded.fillna(False).astype(bool)
    assert lt.sum() > 0 and ref.sum() > 0 and live.spid[lt].str.contains("lifetime").all()
    assert live.exp[lt & ~ref].isna().all()
    expected = oo.last_purchase[ref] + pd.Timedelta(seconds=shift.iloc[0])
    assert ((live.exp[ref] - expected).dt.total_seconds().abs() <= 1).all()
    assert (live.rev[ref] == 0).all()
    assert live.exp[live.is_sub & ~lt].notna().all()


def test_cancellation_reasons_match(live, offline):
    _, o = offline
    m = live.is_sub
    lv, ov = live.reason[m].fillna("-"), o.reindex(live.index).reason[m].fillna("-")
    assert (lv == ov).all(), pd.crosstab(lv, ov)


def test_current_offer_matches_last_receipt(live, offline):
    """Adapty reports the offer of the latest receipt: free_trial only for users whose last receipt is a trial."""
    _, o = offline
    m = live.is_sub
    lv = live.offer[m] == "free_trial"
    ov = o.reindex(live.index).last_offer[m] == "free_trial"
    assert ov.sum() > 0 and (lv == ov).all(), f"{(lv != ov).sum()} mismatches"


def test_one_constant_time_shift(shift):
    assert len(shift) > 1000
    assert shift.max() - shift.min() <= 1, shift.describe()
    assert 0 < shift.iloc[0] < 30 * 86400  # history was moved forward by days, not months


def test_expiry_shifted_or_refund_rule(live, offline, shift):
    """Live expiry = offline expiry + shift; for a refunded last receipt Adapty sets expiry to its purchase time."""
    _, o = offline
    s = shift.iloc[0]
    oo = o.reindex(live.index)
    m = live.is_sub & (oo["product"] != "lifetime")
    expected = np.where(oo.last_refunded[m], oo.last_purchase[m] + pd.Timedelta(seconds=s),
                        oo.last_exp[m] + pd.Timedelta(seconds=s))
    diff = (live.exp[m] - pd.to_datetime(expected, utc=True)).dt.total_seconds().abs()
    assert (diff <= 1).all(), f"{(diff > 1).sum()} expiry mismatches"


def test_non_payers_have_zero_revenue(live, offline):
    _, o = offline
    free = o.reindex(live.index).net_local.fillna(0) == 0
    assert (live.rev[free] == 0).all()


def test_usd_revenue_exact_net_of_refunds(live, offline):
    _, o = offline
    oo = o.reindex(live.index)
    m = (oo.currency == "USD") & (oo.net_local > 0)
    assert m.sum() > 100
    assert ((live.rev[m] - oo.net_usd[m]).abs() < 0.011).all()


def test_non_usd_revenue_is_net_local_times_fx(live, offline):
    """Adapty converts local prices at its own (daily) FX rates: revenue / net local price must be ~constant
    per currency, and much more so than against gross (refunds included)."""
    _, o = offline
    oo = o.reindex(live.index)
    m = (oo.currency != "USD") & (oo.net_local > 0) & oo.currency.notna()
    net = (live.rev[m] / oo.net_local[m]).groupby(oo.currency[m])
    gross = (live.rev[m] / oo.gross_local[m]).groupby(oo.currency[m])
    cv_net = net.std() / net.median()
    cv_gross = gross.std() / gross.median()
    assert (cv_net < 0.05).all(), cv_net.round(4).to_dict()
    assert cv_net.mean() < cv_gross.mean()


# ------------------------------------------------------------------ today's users
def test_todays_users_copy_their_source(snap, run_id, offline):
    if not LIVE_EVERY:
        pytest.skip("no 'installed today' users in this app")
    users, _ = offline
    bad = []
    for i in range(0, N_HIST, LIVE_EVERY):
        p = snap[f"lumen_{run_id}_L{i:05d}"]
        a = {x["key"]: x["value"] for x in p.get("custom_attributes") or []}
        src = users.loc[f"u{i:05d}"]
        if str(a.get("acquisition_channel")) != str(src.acquisition_channel) or str(a.get("app_version")) != str(src.app_version):
            bad.append(i)
    assert not bad, bad[:10]


def test_todays_purchases_are_recent_and_from_payers(snap, run_id, offline, live):
    if not LIVE_EVERY:
        pytest.skip("no 'installed today' users in this app")
    _, o = offline
    newest_hist = live.orig.max()
    n_buy = 0
    for i in range(0, N_HIST, LIVE_EVERY):
        p = snap[f"lumen_{run_id}_L{i:05d}"]
        items = (p.get("subscriptions") or []) + (p.get("non_subscriptions") or [])
        if items:
            n_buy += 1
            assert pd.notna(o["product"].get(f"u{i:05d}")), f"L{i:05d} bought but its source never did"
            t = pd.to_datetime(items[0].get("originally_purchased_at") or items[0].get("purchased_at"), utc=True)
            assert t >= newest_hist - pd.Timedelta(days=1)
    assert n_buy > 0


# ------------------------------------------------------------------ what the Discount Advisor relies on
def test_live_conversion_and_mix_match_offline_subset(live, offline):
    _, o = offline
    oo = o.reindex(live.index)
    assert (live.n_items > 0).mean() == pytest.approx(oo["product"].notna().mean())
    lm = live.spid[live.n_items > 0].str.replace("_", ".", n=1).str.split(":").str[0].value_counts(normalize=True)
    om = oo.spid.dropna().str.replace("_", ".", n=1).str.split(":").str[0].value_counts(normalize=True)
    pd.testing.assert_series_equal(lm.sort_index(), om.sort_index(), check_names=False)


def test_live_sample_consistent_with_50k_population(live, ds):
    """The live users are the first N of the 50,000 offline users: their paid conversion should sit inside
    the sampling interval around the full-population rate (a check that the offline file is representative)."""
    from metrics import wilson_ci
    pop = ds.users
    first = pop[pop.user_id.isin(live.index)]
    p_pop = pop.converted.mean()
    k, n = int(first.converted.sum()), len(first)
    lo, hi = wilson_ci(k, n)
    assert lo <= p_pop <= hi, (k / n, p_pop, lo, hi)
