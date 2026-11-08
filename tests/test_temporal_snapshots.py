"""Point-in-time snapshots: features use only past events, censoring, labels (ml/temporal_churn/snapshots.py)."""
import numpy as np
import pandas as pd
import pytest

pytest.importorskip("pandas")
from ml.temporal_churn import snapshots as S  # noqa: E402

T = pd.Timestamp("2026-08-01T00:00:00Z")
DAY = pd.Timedelta(days=1)


def _users(*ids):
    return pd.DataFrame({
        "user_id": list(ids), "platform": "iOS", "country": "US", "acquisition_channel": "organic",
        "onboarding_goal": "travel", "push_opt_in": "yes", "app_version": "3.6.0", "placement": "main",
        "flow": "main", "ai_edits_first_day": 3.0, "photos_imported": 10.0,
        "install_at": T - 2 * DAY, "price_index": 1.0, "ab_test": None, "locale": "en_US"})


def _tx(user, periods, **last):
    """`periods` weekly paid receipts starting at T; keyword overrides apply to the last receipt."""
    rows = []
    for k in range(periods):
        rows.append({"user_id": user, "seq": k, "product": "weekly", "purchase_type": "subscription",
                     "offer": None, "price_usd": 6.99, "purchased_at": T + 7 * k * DAY,
                     "expires_at": T + 7 * (k + 1) * DAY, "renew_status": True, "renew_status_changed_at": pd.NaT,
                     "refunded_at": pd.NaT, "billing_issue_detected_at": pd.NaT})
    rows[-1].update(last)
    return rows


def _frames(*chains):
    tx = pd.DataFrame([r for c in chains for r in c])
    for c in ["purchased_at", "expires_at", "renew_status_changed_at", "refunded_at", "billing_issue_detected_at"]:
        tx[c] = pd.to_datetime(tx[c], utc=True)
    return _users(*tx["user_id"].unique()), tx


def test_cadence_label_and_temporal_features():
    users, tx = _frames(_tx("a", 3, renew_status=False))      # 3 paid weeks, then no renewal
    s = S.build_snapshots(users, tx, cutoff=T + 60 * DAY)
    assert len(s) == 3 * 7                                     # daily snapshots, day 0..6 of each week
    by_seq = s.groupby("seq")
    assert by_seq["churn"].first().tolist() == [0.0, 0.0, 1.0]  # only the last period fails to renew
    assert by_seq["renewal_count"].first().tolist() == [0.0, 1.0, 2.0]
    first = s[s.seq == 0].sort_values("as_of_at")
    assert first["days_until_renewal"].tolist() == [7, 6, 5, 4, 3, 2, 1]
    assert first["days_since_last_payment"].tolist() == [0, 1, 2, 3, 4, 5, 6]
    assert np.isnan(first["historical_renewal_success_rate"]).all()
    assert (s[s.seq > 0]["historical_renewal_success_rate"] == 1.0).all()


def test_auto_renew_off_only_after_it_happens():
    change = T + 14 * DAY + 3.5 * DAY                          # mid-way through the 3rd week
    users, tx = _frames(_tx("a", 3, renew_status=False, renew_status_changed_at=change))
    s = S.build_snapshots(users, tx, cutoff=T + 60 * DAY)
    assert not s.loc[s.as_of_at < change, "auto_renew_off"].any()
    after = s[s.as_of_at >= change]
    assert after["auto_renew_off"].all() and len(after) == 3
    assert after["days_since_auto_renew_off"].min() == pytest.approx(0.5)


def test_censoring_unresolved_renewals_have_no_label():
    users, tx = _frames(_tx("a", 2))
    cutoff = T + 13 * DAY                                      # second period ends at T+14d: unresolved
    s = S.build_snapshots(users, tx, cutoff=cutoff)
    assert s["as_of_at"].max() <= cutoff
    assert s[s.seq == 0]["churn"].notna().all()
    assert s[s.seq == 1]["churn"].isna().all()


def test_refunded_period_stops_at_refund():
    users, tx = _frames(_tx("a", 1, refunded_at=T + 2.5 * DAY, renew_status=False))
    s = S.build_snapshots(users, tx, cutoff=T + 30 * DAY)
    assert s["as_of_at"].max() < T + 2.5 * DAY and len(s) == 3   # days 0, 1, 2 only
    assert (s["churn"] == 1).all()


def test_billing_issue_counted_only_inside_lookback_and_before_as_of():
    users, tx = _frames(_tx("a", 2, billing_issue_detected_at=T + 10 * DAY))
    s = S.build_snapshots(users, tx, cutoff=T + 60 * DAY)
    assert (s.loc[s.as_of_at < T + 10 * DAY, "billing_issues_last_30d"] == 0).all()
    assert (s.loc[s.as_of_at >= T + 10 * DAY, "billing_issues_last_30d"] == 1).all()


def test_future_events_do_not_change_past_features():
    """Changing everything after a snapshot (renewals, cancellation, refunds) must not change its features."""
    users, tx = _frames(_tx("a", 4), _tx("b", 2, renew_status=False))
    pivot = T + 9 * DAY
    base = S.build_snapshots(users, tx, cutoff=T + 60 * DAY)
    tx2 = tx.copy()
    later = tx2.purchased_at > pivot
    tx2.loc[later, "price_usd"] = 99.0
    tx2.loc[tx2.user_id == "a", "renew_status_changed_at"] = T + 20 * DAY
    tx2.loc[tx2.user_id == "a", "billing_issue_detected_at"] = T + 25 * DAY
    alt = S.build_snapshots(users, tx2, cutoff=T + 60 * DAY)
    feats = S.FEATURE_SETS["temporal_extended"] + S.ROUND2_FEATURES + S.REVENUE_FEATURES
    a = base[base.as_of_at <= pivot].set_index(["user_id", "as_of_at"])[feats]
    b = alt[alt.as_of_at <= pivot].set_index(["user_id", "as_of_at"])[feats]
    pd.testing.assert_frame_equal(a.sort_index(), b.sort_index())


def _receipt(user, seq, product, start_days, length_days, price, **kw):
    row = {"user_id": user, "seq": seq, "product": product, "purchase_type": "subscription", "offer": None,
           "price_usd": price, "purchased_at": T + start_days * DAY, "expires_at": T + (start_days + length_days) * DAY,
           "renew_status": True, "renew_status_changed_at": pd.NaT, "refunded_at": pd.NaT,
           "billing_issue_detected_at": pd.NaT}
    row.update(kw)
    return row


def test_offer_features_trial_then_paid():
    chain = [_receipt("a", 0, "weekly", -3, 3, 0.0, offer="free_trial"),
             _receipt("a", 1, "weekly", 0, 7, 6.99), _receipt("a", 2, "weekly", 7, 7, 6.99)]
    users, tx = _frames(chain)
    s = S.build_snapshots(users, tx, cutoff=T + 60 * DAY)
    assert s[s.seq == 1]["first_renewal_after_offer"].all() and (s[s.seq == 1]["paid_periods_since_offer"] == 1).all()
    assert not s[s.seq == 2]["first_renewal_after_offer"].any() and (s[s.seq == 2]["paid_periods_since_offer"] == 2).all()
    direct, = [_receipt("b", 0, "weekly", 0, 7, 6.99)]
    users, tx = _frames([direct])
    s = S.build_snapshots(users, tx, cutoff=T + 60 * DAY)
    assert not s["first_renewal_after_offer"].any() and s["paid_periods_since_offer"].isna().all()


def test_plan_change_counted_from_switch_onwards():
    chain = [_receipt("a", 0, "weekly", 0, 7, 6.99), _receipt("a", 1, "monthly", 7, 30, 12.99)]
    users, tx = _frames(chain)
    s = S.build_snapshots(users, tx, cutoff=T + 60 * DAY)
    assert (s[s.as_of_at < T + 7 * DAY]["plan_changes"] == 0).all()
    assert (s[s.as_of_at >= T + 7 * DAY]["plan_changes"] == 1).all()


def test_toggles_count_both_directions_and_recency():
    chain = [_receipt("a", 0, "weekly", 0, 7, 6.99, renew_status_changed_at=T + 2 * DAY),
             _receipt("a", 1, "weekly", 7, 7, 6.99, renew_status=False, renew_status_changed_at=T + 9 * DAY)]
    users, tx = _frames(chain)
    s = S.build_snapshots(users, tx, cutoff=T + 60 * DAY).set_index("as_of_at")
    assert s.loc[T + 1 * DAY, "auto_renew_toggles"] == 0 and np.isnan(s.loc[T + 1 * DAY, "days_since_auto_renew_change"])
    assert s.loc[T + 3 * DAY, "auto_renew_toggles"] == 1 and s.loc[T + 3 * DAY, "days_since_auto_renew_change"] == 1
    assert s.loc[T + 10 * DAY, "auto_renew_toggles"] == 2 and s.loc[T + 10 * DAY, "days_since_auto_renew_change"] == 1


def test_price_median_uses_only_past_receipts():
    a = [_receipt("a", 0, "weekly", 0, 7, 4.0)]
    b = [_receipt("b", 0, "weekly", 3, 7, 8.0)]           # a pricier receipt that only exists from day 3
    users, tx = _frames(a, b)
    s = S.build_snapshots(users, tx, cutoff=T + 60 * DAY)
    sa = s[s.user_id == "a"].set_index("as_of_at")["price_vs_country_median"]
    assert sa.loc[T + 1 * DAY] == 1.0                     # only a's own receipt is known
    assert sa.loc[T + 4 * DAY] == pytest.approx(4.0 / 6.0)  # median of 4 and 8 once b's receipt exists


def test_prior_refunds_counted_after_they_happen():
    chain = [_receipt("a", 0, "weekly", 0, 7, 6.99, refunded_at=T + 6.5 * DAY),
             _receipt("a", 1, "weekly", 7, 7, 6.99)]
    users, tx = _frames(chain)
    s = S.build_snapshots(users, tx, cutoff=T + 60 * DAY)
    assert (s[s.seq == 0]["prior_refunds"] == 0).all() and (s[s.seq == 1]["prior_refunds"] == 1).all()


def test_cancellation_reason_is_never_used():
    users, tx = _frames(_tx("a", 3, renew_status=False), _tx("b", 2))
    tx_a = tx.assign(cancellation_reason=None)
    tx_b = tx.assign(cancellation_reason="voluntarily_cancelled")
    feats = S.FEATURE_SETS["temporal_extended"] + S.ROUND2_FEATURES + S.REVENUE_FEATURES
    pd.testing.assert_frame_equal(S.build_snapshots(users, tx_a, T + 60 * DAY)[feats],
                                  S.build_snapshots(users, tx_b, T + 60 * DAY)[feats])


def test_switch_off_timing_within_period():
    change = T + 3.5 * DAY                                    # half-way through a 7-day period
    users, tx = _frames(_tx("a", 1, renew_status=False, renew_status_changed_at=change))
    s = S.build_snapshots(users, tx, cutoff=T + 30 * DAY).set_index("as_of_at")
    assert np.isnan(s.loc[T + 3 * DAY, "auto_renew_off_period_fraction"])     # not switched off yet
    assert s.loc[T + 4 * DAY, "auto_renew_off_period_fraction"] == pytest.approx(0.5)
    # leaving window = 3.5 days (switch-off -> renewal due); at day 6, 2.5 days of it have passed
    assert s.loc[T + 6 * DAY, "leaving_window_elapsed"] == pytest.approx(2.5 / 3.5)


def test_cohort_rate_uses_only_renewals_resolved_before_the_snapshot():
    # b churns at its renewal on day 7 (same channel/country/paywall as a); a's later snapshots may see it, earlier ones not
    users, tx = _frames(_tx("a", 3), _tx("b", 1, renew_status=False))
    s = S.build_snapshots(users, tx, cutoff=T + 60 * DAY)
    a = s[s.user_id == "a"].set_index("as_of_at")
    before, after = a.loc[T + 6 * DAY], a.loc[T + 7 * DAY]
    assert before["cohort_churn_rate_channel"] == 0.0         # no resolved renewal yet
    # at day 7: a renewed (0) and b churned (1) -> 1 churn / 2 renewals; prior = overall rate so far (also 1/2)
    assert after["cohort_churn_rate_channel"] == pytest.approx(0.5)
    assert after["cohort_churn_rate_country"] == after["cohort_churn_rate_paywall"] == after["cohort_churn_rate_channel"]


def test_install_and_first_purchase_features():
    users, tx = _frames(_tx("a", 1))
    s = S.build_snapshots(users, tx, cutoff=T + 30 * DAY)
    assert (s["days_install_to_first_purchase"] == 2.0).all()
    assert (s["install_hour_utc"] == 0).all() and (s["install_weekday_utc"] == (T - 2 * DAY).day_of_week).all()
    assert (s["ab_test"] == "none").all() and (s["first_offer"] == "none").all() and (s["locale"] == "en_US").all()


def test_cumulative_net_revenue_is_point_in_time():
    chain = [_receipt("a", 0, "weekly", 0, 7, 6.99, refunded_at=T + 6.5 * DAY),   # refunded late in week 1
             _receipt("a", 1, "weekly", 7, 7, 6.99), _receipt("a", 2, "weekly", 14, 7, 6.99)]
    users, tx = _frames(chain)
    s = S.build_snapshots(users, tx, cutoff=T + 60 * DAY).set_index("as_of_at")
    assert s.loc[T + 1 * DAY, "cumulative_net_revenue_usd"] == pytest.approx(6.99)       # before the refund
    assert s.loc[T + 8 * DAY, "cumulative_net_revenue_usd"] == pytest.approx(6.99)       # 2 payments - 1 refund
    assert s.loc[T + 15 * DAY, "cumulative_net_revenue_usd"] == pytest.approx(13.98)     # 3 payments - 1 refund
    # per subscribed day: tenure counts from the first paid receipt, floored at 1 day
    assert s.loc[T, "revenue_per_subscribed_day"] == pytest.approx(6.99)
    assert s.loc[T + 15 * DAY, "revenue_per_subscribed_day"] == pytest.approx(13.98 / 15)


def test_feature_record_is_json_ready():
    users, tx = _frames(_tx("a", 1))
    rec = S.feature_record(S.build_snapshots(users, tx, cutoff=T + 30 * DAY).iloc[0])
    assert set(rec) == set(S.FEATURE_SETS["temporal"])
    assert rec["historical_renewal_success_rate"] is None and rec["auto_renew_off"] is False
    assert isinstance(rec["plan"], str) and isinstance(rec["tenure_days"], float)


# ---------------------------------------------------------------- real dataset (skipped if absent)
@pytest.fixture(scope="module")
def real():
    try:
        users, tx, cutoff = S.load()
    except FileNotFoundError:
        pytest.skip("Lumen offline data not available (set LUMEN_DATA_DIR)")
    return users, tx, cutoff, S.build_snapshots(users, tx, cutoff)


def test_real_cutoff_is_an_observed_event(real):
    _, tx, cutoff, s = real
    assert cutoff < tx["expires_at"].max()
    assert s["as_of_at"].max() <= cutoff


def test_real_censoring_rule(real):
    _, _, cutoff, s = real
    resolved = s["renewal_due_at"] <= cutoff - pd.Timedelta(days=S.OUTCOME_MARGIN_DAYS)
    assert (s["churn"].notna() == resolved).all()
    assert s["churn"].isna().sum() > 0


def test_real_labels_match_chain_end(real):
    _, tx, _, s = real
    paid = tx[tx["product"].isin(S.PLANS) & (tx["price_usd"] > 0)]
    last_seq = paid.groupby("user_id")["seq"].max()
    lab = s[s["churn"].notna()]
    is_last = lab["seq"].values == last_seq.reindex(lab["user_id"]).values
    assert ((lab["churn"] == 1).values == is_last).all()
