"""Data integrity and semantics: derived tables must agree with the raw CSVs and the documented rules."""
import pandas as pd
import pytest

from data import CONVERSION_WINDOW_DAYS, _build_chains, observation_cutoff


# ---------------------------------------------------------------- structure
def test_row_counts_preserved(ds, raw):
    u, t = raw
    assert len(ds.users) == len(u)
    assert len(ds.tx) == len(t)  # the user-attribute merge must not duplicate or drop receipts


def test_keys_unique(ds):
    assert ds.users.user_id.is_unique
    assert not ds.tx.duplicated(["user_id", "seq"]).any()
    assert ds.chains.user_id.is_unique


def test_every_receipt_has_an_install(ds):
    assert ds.tx.country.notna().all()


def test_one_chain_and_one_product_per_user(raw):
    _, t = raw
    assert t.groupby("user_id")["originally_purchased_at"].nunique().max() <= 1
    assert t.groupby("user_id")["product"].nunique().max() == 1


def test_receipts_are_contiguous(ds):
    t = ds.tx.sort_values(["user_id", "seq"])
    assert t.groupby("user_id")["seq"].apply(lambda s: list(s) == list(range(len(s)))).all()
    nxt = t.groupby("user_id")["purchased_at"].shift(-1)
    gap = (nxt - t["expires_at"]).dropna().dt.total_seconds().abs()
    assert gap.max() == 0


def test_trials_are_free_first_receipts(ds):
    trials = ds.tx[ds.tx.offer == "free_trial"]
    assert (trials.price_usd == 0).all() and (trials.seq == 0).all()
    assert not trials.is_paid.any()


def test_each_install_has_one_placement(ds):
    assert ds.users.placement.notna().all()


# ---------------------------------------------------------------- cutoff and censoring
def test_cutoff_is_last_observed_event_not_expiry(ds):
    assert ds.as_of == observation_cutoff(ds.users, ds.tx)
    assert ds.as_of < ds.tx.expires_at.max()  # future expiries exist and were ignored
    assert ds.as_of >= ds.tx.purchased_at.max()
    for c in ["renew_status_changed_at", "refunded_at", "billing_issue_detected_at"]:
        assert ds.as_of >= ds.tx[c].max()


def test_censored_iff_open_period_and_not_refunded(ds):
    last = ds.tx[ds.tx.is_paid].sort_values("seq").groupby("user_id").tail(1).set_index("user_id")
    ch = ds.chains.set_index("user_id")
    expected = ch.is_subscription & (last.expires_at > ds.as_of).reindex(ch.index) & last.refunded_at.isna().reindex(ch.index)
    assert (ch.censored == expected).all()
    assert not ch[ch["product"] == "lifetime"].censored.any()


def test_auto_renew_off_but_period_open_is_censored(ds):
    """Cancelling auto-renew mid-period must not count as an observed churn before the period ends."""
    last = ds.tx[ds.tx.is_paid].sort_values("seq").groupby("user_id").tail(1).set_index("user_id")
    cancelled_open = last[(last.renew_status.astype(str) == "False") & (last.expires_at > ds.as_of)
                          & last.refunded_at.isna()].index
    assert len(cancelled_open) > 0
    assert ds.chains.set_index("user_id").loc[cancelled_open, "censored"].all()


def test_censoring_on_toy_chain():
    as_of = pd.Timestamp("2026-01-10", tz="UTC")
    tx = pd.DataFrame({
        "user_id": ["a", "b", "c", "d"], "seq": 0, "product": "monthly", "purchase_type": "subscription",
        "originally_purchased_at": pd.Timestamp("2026-01-01", tz="UTC"),
        "purchased_at": pd.Timestamp("2026-01-01", tz="UTC"),
        "expires_at": pd.to_datetime(["2026-01-31", "2026-01-05", "2026-01-31", "2026-01-31"], utc=True),
        "price_usd": 10.0, "is_paid": True,
        "refunded_at": [pd.NaT, pd.NaT, pd.Timestamp("2026-01-03", tz="UTC"), pd.NaT],
        "renew_status": [True, False, False, False],
    })
    tx["is_refunded"] = tx.refunded_at.notna()
    tx["net_usd"] = tx.price_usd.where(~tx.is_refunded, 0.0)
    ch = _build_chains(tx, as_of).set_index("user_id")
    assert ch.loc["a", "censored"]          # open, auto-renew on
    assert not ch.loc["b", "censored"]      # period ended before cutoff without renewal -> event
    assert not ch.loc["c", "censored"]      # refunded -> event
    assert ch.loc["d", "censored"]          # auto-renew off but period still open -> unknown
    assert ch.loc["c", "observed_net_usd"] == 0 and ch.loc["a", "observed_net_usd"] == 10


# ---------------------------------------------------------------- conversion and maturity
def test_maturity_rule(ds):
    cut = ds.as_of - pd.Timedelta(days=CONVERSION_WINDOW_DAYS)
    assert (ds.users.mature == (ds.users.install_at <= cut)).all()
    assert 0 < (~ds.users.mature).sum() < len(ds.users)


def test_window_covers_every_observed_first_payment(ds):
    assert ds.users.days_to_first_paid.max() <= CONVERSION_WINDOW_DAYS
    assert (ds.users.days_to_first_paid.dropna() >= 0).all()


def test_converted_means_paid_within_window(ds, raw):
    _, t = raw
    payers = set(t[t.price_usd > 0].user_id)
    u = ds.users
    assert (u.converted == u.user_id.isin(payers) & (u.days_to_first_paid <= CONVERSION_WINDOW_DAYS)).all()


def test_trial_only_users_are_not_payers(ds, raw):
    _, t = raw
    trial_only = set(t.user_id) - set(t[t.price_usd > 0].user_id)
    assert len(trial_only) > 0
    assert not ds.users.set_index("user_id").loc[list(trial_only), "converted"].any()


def test_refunded_first_receipt_still_counts_as_conversion(ds):
    first = ds.tx[ds.tx.is_paid].sort_values("seq").groupby("user_id").head(1)
    refunded_first = first[first.is_refunded].user_id
    assert len(refunded_first) > 0
    assert ds.users.set_index("user_id").loc[refunded_first, "converted"].all()


# ---------------------------------------------------------------- chains and refunds
def test_chain_paid_periods_match_raw(ds, raw):
    _, t = raw
    paid = t[t.price_usd > 0].groupby("user_id").size()
    c = ds.chains.set_index("user_id")["paid_periods"]
    assert (c.sort_index() == paid.sort_index()).all()


def test_first_price_is_first_paid_receipt(ds, raw):
    _, t = raw
    first = t[t.price_usd > 0].sort_values(["user_id", "seq"]).groupby("user_id").price_usd.first()
    assert (ds.chains.set_index("user_id").first_price_usd.sort_index() - first.sort_index()).abs().max() < 1e-9


def test_observed_net_excludes_refunded_receipts(ds, raw):
    _, t = raw
    p = t[t.price_usd > 0]
    expected = p.price_usd.where(p.refunded_at.isna(), 0).groupby(p.user_id).sum()
    got = ds.chains.set_index("user_id").observed_net_usd
    assert (got.sort_index() - expected.sort_index()).abs().max() < 1e-9


def test_refunds_only_hit_last_receipt(ds):
    last = ds.tx.groupby("user_id").seq.max()
    r = ds.tx[ds.tx.is_refunded]
    assert (r.seq.values == last.reindex(r.user_id).values).all()


def test_lifetime_is_not_a_subscription(ds):
    lt = ds.chains[ds.chains["product"] == "lifetime"]
    assert len(lt) > 0 and not lt.is_subscription.any() and (lt.paid_periods == 1).all()


def test_price_tier_covers_everyone(ds):
    assert ds.users.price_tier.notna().all()
    assert ds.users.price_index.between(0.3, 1.0).all()


def test_missing_data_dir_raises(tmp_path, monkeypatch):
    import data
    monkeypatch.setenv("DISCOUNT_DATA_DIR", str(tmp_path))
    with pytest.raises(FileNotFoundError):
        data.load()
