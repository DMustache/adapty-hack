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
        "install_at": T - 2 * DAY, "price_index": 1.0})


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
    feats = [f for f in S.FEATURE_SETS["temporal"]]
    a = base[base.as_of_at <= pivot].set_index(["user_id", "as_of_at"])[feats]
    b = alt[alt.as_of_at <= pivot].set_index(["user_id", "as_of_at"])[feats]
    pd.testing.assert_frame_equal(a.sort_index(), b.sort_index())


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
