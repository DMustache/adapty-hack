"""live_view on small hand-made snapshots (offline, no network)."""
import json

import pandas as pd
import pytest

import live_view as lv


@pytest.mark.parametrize("spid,key", [("lumen.weekly", "weekly"), ("lumen_weekly", "weekly"),
                                      ("lumen_annual_trial", "annual_trial"), ("lumen.weekly_30off", "weekly_30off"),
                                      ("lumen_weekly:weekly", "weekly"), (None, None)])
def test_product_key(spid, key):
    assert lv.product_key(spid) == key


def _profile(spid=None, reason=None, rev=0.0):
    subs = [{"store_product_id": spid, "cancellation_reason": reason}] if spid else []
    return {"subscriptions": subs, "non_subscriptions": [], "total_revenue_usd": rev}


def test_profiles_frame_marks_missing_and_buyers():
    snap = {"lumen_1_00000": _profile("lumen.weekly", "refund", 6.99), "lumen_1_00001": _profile(),
            "lumen_1_00002": None}
    f = lv.profiles_frame(snap, "1", 3)
    assert f.present.tolist() == [True, True, False]
    assert f.loc["u00000", "buyer"] and not f.loc["u00001", "buyer"]
    assert f.loc["u00000", "product"] == "weekly" and f.loc["u00000", "reason"] == "refund"


def test_live_vs_offline_matches_itself(ds):
    """Build a snapshot that mirrors the offline data for 300 users: every count must match."""
    ids = [f"u{i:05d}" for i in range(300)]
    tx = ds.tx[ds.tx.user_id.isin(ids)].sort_values(["user_id", "seq"])
    first = tx.groupby("user_id").head(1).set_index("user_id")
    last = tx.groupby("user_id").tail(1).set_index("user_id")
    snap = {}
    for i, uid in enumerate(ids):
        if uid in first.index:
            net = float(tx[tx.user_id == uid].pipe(lambda t: t.price_usd.where(t.refunded_at.isna(), 0)).sum())
            snap[f"lumen_9_{i:05d}"] = _profile(f"lumen.{first.loc[uid, 'product']}",
                                                last.loc[uid, "cancellation_reason"] if pd.notna(
                                                    last.loc[uid, "cancellation_reason"]) else None, net)
        else:
            snap[f"lumen_9_{i:05d}"] = _profile()
    t = lv.live_vs_offline(ds, snap, "9", 300).set_index("Measure")
    for measure, row in t.iterrows():
        if measure == "Users found":
            assert row["Live Adapty"].startswith("300")
        else:
            assert row["Live Adapty"] == row["Offline CSV"], measure


def test_experiment_results():
    specs = [{"k": 0, "arm": "control"}, {"k": 1, "arm": "control"}, {"k": 2, "arm": "discount"},
             {"k": 3, "arm": "discount"}]
    snap = {"lumen_7_D0000": _profile("lumen.annual", None, 50.0), "lumen_7_D0001": _profile(),
            "lumen_7_D0002": _profile("lumen.weekly_30off", None, 4.89), "lumen_7_D0003": None}
    r = lv.experiment_results(snap, specs, run_id="7")
    assert r.loc["control", "users"] == 2 and r.loc["control", "buyers"] == 1
    assert r.loc["discount", "users"] == 1 and r.loc["discount", "on_30off_product"] == 1
    assert r.loc["control", "revenue_per_user"] == pytest.approx(25.0)


def test_missing_snapshot_returns_none(tmp_path):
    assert lv.load_snapshot("nope.json", tmp_path) is None
    (tmp_path / "x.json").write_text(json.dumps({"a": 1}))
    assert lv.load_snapshot("x.json", tmp_path) == {"a": 1}
