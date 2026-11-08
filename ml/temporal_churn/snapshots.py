"""Point-in-time subscriber snapshots from the Lumen transactions dataset (SYNTHETIC).

Research code (ML researcher side of docs/MODEL_HANDOFF.md). The services never train or score here; they load the
exported, checksummed artifact through an adapter.

Snapshot = one active weekly/monthly subscriber observed at `as_of_at` inside a paid period:
  * periods: every paid receipt of a weekly or monthly subscription chain (trials are not paid periods)
  * cadence: daily for weekly plans, every 3 days for monthly plans, from the payment (day 0) until the renewal
    is due; only instants up to the observation cutoff (the last observed event, never a future `expires_at`)
  * the subscriber must still be entitled at `as_of_at` (not refunded at or before it)
  * `renewal_due_at` = end of the current paid period = the next eligible renewal event

Label `churn` = 1 if the next renewal does not happen (any reason: voluntary cancellation, billing failure, refund),
else 0. It is only defined when the renewal was resolved before the cutoff: `renewal_due_at <= cutoff - 1 day`.
Later snapshots are CENSORED (`churn` = NaN): they can be scored but never trained or evaluated on.

Every feature uses only events with a timestamp <= `as_of_at` (tests/test_temporal_snapshots.py perturbs future
events to check this).
"""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd

PLANS = ("weekly", "monthly")
CADENCE_DAYS = {"weekly": 1, "monthly": 3}
OUTCOME_MARGIN_DAYS = 1
BILLING_LOOKBACK_DAYS = 30

STATIC_CATEGORICAL = ["plan", "platform", "country", "acquisition_channel", "onboarding_goal", "push_opt_in",
                      "app_version", "placement", "flow"]
STATIC_NUMERIC = ["renewal_price_usd", "price_index", "ai_edits_first_day", "photos_imported"]
STATIC_BOOLEAN = ["started_with_trial"]
TEMPORAL_NUMERIC = ["tenure_days", "renewal_count", "days_until_renewal", "days_since_last_payment",
                    "historical_renewal_success_rate", "billing_issues_last_30d", "days_since_install"]
STATUS_BOOLEAN = ["auto_renew_off"]
STATUS_NUMERIC = ["days_since_auto_renew_off"]

# Subscription-history features (all point-in-time: only events dated <= as_of_at). cancellation_reason is never
# used: it is only known once a subscription has ended. Groups are evaluated one by one in ablation_history.py.
HISTORY_GROUPS = {
    "auto_renew_toggles": ["auto_renew_toggles", "days_since_auto_renew_change"],
    "plan_changes": ["plan_changes"],
    "first_full_price_renewal_after_offer": ["first_renewal_after_offer", "paid_periods_since_offer"],
    "price_vs_country_median": ["price_vs_country_median"],
    "prior_refunds": ["prior_refunds"],
}
HISTORY_BOOLEAN = ["first_renewal_after_offer"]
HISTORY_FEATURES = [f for g in HISTORY_GROUPS.values() for f in g]

# Round 2 candidates (ablation_round2.py). Already in the deployed set, so not repeated: placement, flow,
# acquisition_channel, app_version. Install time is UTC (users.csv has no timezone). Cohort churn rates use only
# renewals resolved at or before as_of_at, smoothed toward the overall rate with COHORT_PRIOR_WEIGHT pseudo-renewals.
ROUND2_GROUPS = {
    "switch_off_timing": ["auto_renew_off_period_fraction", "leaving_window_elapsed"],
    "ab_test": ["ab_test"],
    "first_offer": ["first_offer"],
    "locale": ["locale"],
    "install_time": ["install_hour_utc", "install_weekday_utc"],
    "days_install_to_first_purchase": ["days_install_to_first_purchase"],
    "cohort_churn_rate_channel": ["cohort_churn_rate_channel"],
    "cohort_churn_rate_country": ["cohort_churn_rate_country"],
    "cohort_churn_rate_paywall": ["cohort_churn_rate_paywall"],
}
ROUND2_CATEGORICAL = ["ab_test", "first_offer", "locale"]
ROUND2_FEATURES = [f for g in ROUND2_GROUPS.values() for f in g]
COHORT_PRIOR_WEIGHT = 20

FEATURE_SETS = {
    # attributes known at sign-up only: one value per subscription period, whatever the date
    "static": STATIC_CATEGORICAL + STATIC_NUMERIC + STATIC_BOOLEAN,
    # + how far into the period, how long subscribed, renewal history, billing history (no auto-renew status)
    "temporal_behaviour": STATIC_CATEGORICAL + STATIC_NUMERIC + STATIC_BOOLEAN + TEMPORAL_NUMERIC,
    # + subscription status as of the snapshot (auto-renew switched off, and since when): the deployed model
    "temporal": STATIC_CATEGORICAL + STATIC_NUMERIC + STATIC_BOOLEAN + TEMPORAL_NUMERIC
                + STATUS_BOOLEAN + STATUS_NUMERIC,
}
# candidate set: deployed temporal features + subscription-history features. Evaluated in ablation_history.py;
# not deployed: none of the groups improved the model on this data (2026-11-08).
FEATURE_SETS["temporal_extended"] = FEATURE_SETS["temporal"] + HISTORY_FEATURES
# round-2 candidate set (ablation_round2.py); not deployed unless a group passes the ablation rule
FEATURE_SETS["temporal_round2"] = FEATURE_SETS["temporal"] + ROUND2_FEATURES
EVALUATED_MODELS = ("static", "temporal_behaviour", "temporal")   # trained/compared by train.py and ablation.py
CATEGORICAL = set(STATIC_CATEGORICAL + ROUND2_CATEGORICAL)
BOOLEAN = set(STATIC_BOOLEAN + STATUS_BOOLEAN + HISTORY_BOOLEAN)


def find_data_dir(explicit: str | Path | None = None) -> Path:
    candidates = [explicit, os.environ.get("LUMEN_DATA_DIR")]
    here = Path(__file__).resolve()
    for base in (here.parents[2], here.parents[3]):
        candidates += [base / "adapty-seed-data-hack" / "data" / "offline",
                       base / "PythonProject1" / "adapty-seed-data-hack" / "data" / "offline"]
    for c in candidates:
        if c and (Path(c) / "users.csv.gz").exists():
            return Path(c)
    raise FileNotFoundError("Lumen offline data not found: pass --data-dir or set LUMEN_DATA_DIR "
                            "(folder with users.csv.gz and transactions.csv.gz)")


def _ts(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, utc=True, errors="coerce")


def load(data_dir: str | Path | None = None) -> tuple[pd.DataFrame, pd.DataFrame, pd.Timestamp]:
    d = find_data_dir(data_dir)
    users = pd.read_csv(d / "users.csv.gz")
    tx = pd.read_csv(d / "transactions.csv.gz")
    users["install_at"] = _ts(users["install_at"])
    for c in ["purchased_at", "expires_at", "originally_purchased_at", "renew_status_changed_at",
              "billing_issue_detected_at", "refunded_at"]:
        tx[c] = _ts(tx[c])
    cutoff = observation_cutoff(users, tx)
    annual = tx[(tx["product"] == "annual") & (tx["price_usd"] > 0)].merge(users[["user_id", "country"]], on="user_id")
    users["price_index"] = users["country"].map((annual.groupby("country")["price_usd"].median() / 49.99).round(2))
    return users, tx, cutoff


def observation_cutoff(users: pd.DataFrame, tx: pd.DataFrame) -> pd.Timestamp:
    """Latest timestamp of an event that actually happened (never a scheduled `expires_at`)."""
    return max(users["install_at"].max(), tx["purchased_at"].max(), tx["renew_status_changed_at"].max(),
               tx["billing_issue_detected_at"].max(), tx["refunded_at"].max())


def periods(tx: pd.DataFrame) -> pd.DataFrame:
    """One row per paid weekly/monthly period, with its chain position and what happened next."""
    t = tx[tx["product"].isin(PLANS) & (tx["purchase_type"] == "subscription")].sort_values(["user_id", "seq"])
    trial_users = set(t.loc[t["offer"] == "free_trial", "user_id"])
    p = t[t["price_usd"] > 0].copy()
    p["k"] = p.groupby("user_id").cumcount() + 1
    p["n_paid"] = p.groupby("user_id")["k"].transform("max")
    p["first_paid_at"] = p.groupby("user_id")["purchased_at"].transform("min")
    p["renewed"] = p["k"] < p["n_paid"]
    p["started_with_trial"] = p["user_id"].isin(trial_users)
    # billing-issue timestamps of the whole chain, to count only those seen before each snapshot
    return p.reset_index(drop=True)


def build_snapshots(users: pd.DataFrame, tx: pd.DataFrame, cutoff: pd.Timestamp,
                    user_ids: set[str] | None = None) -> pd.DataFrame:
    """All point-in-time snapshots up to `cutoff` (labelled where the outcome is resolved, else NaN)."""
    p = periods(tx)
    if user_ids is not None:
        p = p[p["user_id"].isin(user_ids)]
    rows = []
    for r in p.itertuples(index=False):
        step = pd.Timedelta(days=CADENCE_DAYS[r.product])
        t = r.purchased_at
        while t < r.expires_at and t <= cutoff:
            if not (pd.notna(r.refunded_at) and r.refunded_at <= t):
                rows.append((r.user_id, r.seq, r.k, r.product, float(r.price_usd), t, r.expires_at, r.purchased_at,
                             r.first_paid_at, bool(r.started_with_trial), bool(r.renewed), r.renew_status,
                             r.renew_status_changed_at, r.refunded_at))
            t = t + step
    s = pd.DataFrame(rows, columns=["user_id", "seq", "k", "plan", "renewal_price_usd", "as_of_at", "renewal_due_at",
                                    "last_payment_at", "first_paid_at", "started_with_trial", "renewed",
                                    "renew_status", "renew_status_changed_at", "refunded_at"])
    if s.empty:
        return s
    for c in ["as_of_at", "renewal_due_at", "last_payment_at", "first_paid_at", "renew_status_changed_at",
              "refunded_at"]:
        s[c] = pd.to_datetime(s[c], utc=True)          # keep UTC even when a column holds only NaT
    day = pd.Timedelta(days=1)
    s["tenure_days"] = (s["as_of_at"] - s["first_paid_at"]) / day
    s["renewal_count"] = (s["k"] - 1).astype(float)                     # renewals that already happened
    s["days_until_renewal"] = (s["renewal_due_at"] - s["as_of_at"]) / day
    s["days_since_last_payment"] = (s["as_of_at"] - s["last_payment_at"]) / day
    # a chain ends at its first failed renewal, so every past renewal attempt of an active subscriber succeeded;
    # null before the first renewal attempt
    s["historical_renewal_success_rate"] = np.where(s["k"] > 1, 1.0, np.nan)
    # auto-renew status as of the snapshot: only the receipt that carries the change can show it
    off = (s["renew_status"].astype(str) == "False") & s["renew_status_changed_at"].notna() \
        & (s["renew_status_changed_at"] <= s["as_of_at"])
    s["auto_renew_off"] = off
    s["days_since_auto_renew_off"] = np.where(off, (s["as_of_at"] - s["renew_status_changed_at"]) / day, np.nan)
    s["billing_issues_last_30d"] = _billing_counts(s, tx)
    u = users.set_index("user_id")
    s = s.join(u[["platform", "country", "acquisition_channel", "onboarding_goal", "push_opt_in", "app_version",
                  "placement", "flow", "ai_edits_first_day", "photos_imported", "install_at", "price_index"]],
               on="user_id")
    s["platform"] = s["platform"].str.lower()
    s["app_version"] = s["app_version"].astype(str)
    s["days_since_install"] = (s["as_of_at"] - s["install_at"]) / day
    s = s.reset_index(drop=True)
    _add_history_features(s, users, tx)
    _add_round2_features(s, users, tx, off)
    resolved = s["renewal_due_at"] <= cutoff - pd.Timedelta(days=OUTCOME_MARGIN_DAYS)
    s["churn"] = np.where(resolved, (~s["renewed"]).astype(float), np.nan)
    keep = ["user_id", "seq", "as_of_at", "renewal_due_at", "churn"] + FEATURE_SETS["temporal_extended"] \
        + ROUND2_FEATURES
    return s[keep].sort_values(["as_of_at", "user_id"]).reset_index(drop=True)


def _add_round2_features(s: pd.DataFrame, users: pd.DataFrame, tx: pd.DataFrame, off: pd.Series) -> None:
    day = pd.Timedelta(days=1)
    off = off.to_numpy()
    # (1) when in the billing period auto-renew was switched off, and how much of the remaining "leaving window"
    # (switch-off -> renewal due) has elapsed; null until a switch-off has happened
    period = (s["renewal_due_at"] - s["last_payment_at"]) / day
    s["auto_renew_off_period_fraction"] = np.where(
        off, (s["renew_status_changed_at"] - s["last_payment_at"]) / day / period, np.nan)
    window = (s["renewal_due_at"] - s["renew_status_changed_at"]) / day
    s["leaving_window_elapsed"] = np.where(
        off, ((s["as_of_at"] - s["renew_status_changed_at"]) / day) / window.where(window > 0), np.nan)
    # (2) acquisition context known at install / first purchase
    u = users.set_index("user_id")
    s["ab_test"] = s["user_id"].map(u["ab_test"]).fillna("none").astype(str)
    s["locale"] = s["user_id"].map(u["locale"]).astype(str)
    s["install_hour_utc"] = s["install_at"].dt.hour.astype(float)
    s["install_weekday_utc"] = s["install_at"].dt.day_of_week.astype(float)
    first = tx.sort_values(["user_id", "purchased_at", "seq"]).groupby("user_id").head(1).set_index("user_id")
    s["first_offer"] = s["user_id"].map(first["offer"]).fillna("none").astype(str)
    s["days_install_to_first_purchase"] = (s["user_id"].map(first["purchased_at"]) - s["install_at"]) / day
    # (3) point-in-time cohort churn rates: renewal outcomes of weekly/monthly periods resolved at or before as_of_at
    p = periods(tx).merge(users[["user_id", "acquisition_channel", "country", "flow"]], on="user_id")
    ev = pd.DataFrame({"t": p["expires_at"], "churn": (~p["renewed"]).astype(float),
                       "acquisition_channel": p["acquisition_channel"], "country": p["country"], "flow": p["flow"]})
    ev = ev[ev["t"].notna()].sort_values("t")
    ev["g_n"] = np.arange(1, len(ev) + 1, dtype=float)
    ev["g_churn"] = ev["churn"].cumsum()
    left = s[["as_of_at", "acquisition_channel", "country", "flow"]].reset_index().rename(columns={"index": "row"}) \
        .sort_values("as_of_at")
    glob = pd.merge_asof(left, ev[["t", "g_n", "g_churn"]], left_on="as_of_at", right_on="t",
                         direction="backward").set_index("row").reindex(s.index)
    prior = (glob["g_churn"] / glob["g_n"]).fillna(0.0)               # overall rate so far (0 before any outcome)
    for col, name in (("acquisition_channel", "cohort_churn_rate_channel"), ("country", "cohort_churn_rate_country"),
                      ("flow", "cohort_churn_rate_paywall")):
        e = ev[["t", col, "churn"]].copy()
        e["n"] = e.groupby(col).cumcount() + 1.0
        e["c"] = e.groupby(col)["churn"].cumsum()
        m = pd.merge_asof(left, e[["t", col, "n", "c"]], left_on="as_of_at", right_on="t", by=col,
                          direction="backward").set_index("row").reindex(s.index)
        n, c = m["n"].fillna(0.0), m["c"].fillna(0.0)
        s[name] = (c + COHORT_PRIOR_WEIGHT * prior) / (n + COHORT_PRIOR_WEIGHT)


def _events_up_to(s: pd.DataFrame, events: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """For each snapshot row: number of the subscriber's events with t <= as_of_at, and the latest such t."""
    if events.empty:
        return pd.Series(0.0, index=s.index), pd.Series(pd.NaT, index=s.index, dtype="datetime64[ns, UTC]")
    snap = s[["user_id", "as_of_at"]].reset_index().rename(columns={"index": "row"})
    m = snap.merge(events[["user_id", "t"]], on="user_id")
    m = m[m["t"] <= m["as_of_at"]]
    g = m.groupby("row")["t"]
    return (g.size().reindex(s.index, fill_value=0).astype(float),
            g.max().reindex(s.index).astype("datetime64[ns, UTC]"))


def _add_history_features(s: pd.DataFrame, users: pd.DataFrame, tx: pd.DataFrame) -> None:
    day = pd.Timedelta(days=1)
    t = tx.sort_values(["user_id", "purchased_at", "seq"])
    # auto-renew toggles: every recorded renew-status change (either direction)
    toggles = t.loc[t["renew_status_changed_at"].notna(), ["user_id", "renew_status_changed_at"]] \
        .rename(columns={"renew_status_changed_at": "t"})
    s["auto_renew_toggles"], last_toggle = _events_up_to(s, toggles)
    s["days_since_auto_renew_change"] = (s["as_of_at"] - last_toggle) / day
    # plan changes: a receipt whose product differs from the subscriber's previous receipt
    prev = t.groupby("user_id")["product"].shift()
    changes = t.loc[prev.notna() & (t["product"] != prev), ["user_id", "purchased_at"]].rename(columns={"purchased_at": "t"})
    s["plan_changes"], _ = _events_up_to(s, changes)
    # offers (intro/promo, incl. free trials): paid periods since the latest offer; the period right after it ends in
    # the first full-price renewal
    offers = t.loc[t["offer"].notna(), ["user_id", "purchased_at"]].rename(columns={"purchased_at": "t"})
    n_offers, last_offer = _events_up_to(s, offers)
    paid = t.loc[t["price_usd"] > 0, ["user_id", "purchased_at"]].rename(columns={"purchased_at": "t"})
    snap = s[["user_id", "as_of_at"]].assign(last_offer=last_offer).reset_index().rename(columns={"index": "row"})
    m = snap.merge(paid, on="user_id")
    m = m[(m["t"] <= m["as_of_at"]) & m["last_offer"].notna() & (m["t"] > m["last_offer"])]
    since = m.groupby("row").size().reindex(s.index, fill_value=0).astype(float)
    s["paid_periods_since_offer"] = np.where(n_offers > 0, since, np.nan)
    s["first_renewal_after_offer"] = (n_offers > 0) & (since == 1)
    # price vs the median paid price of the same product in the same country, from receipts up to as_of_at only
    country = users.set_index("user_id")["country"]
    pr = t.loc[t["price_usd"] > 0, ["user_id", "product", "purchased_at", "price_usd"]].copy()
    pr["country"] = pr["user_id"].map(country)
    pr = pr.sort_values("purchased_at")
    pr["median"] = pr.groupby(["country", "product"])["price_usd"].transform(lambda x: x.expanding().median())
    left = s[["as_of_at", "country", "plan"]].reset_index().rename(columns={"index": "row"}).sort_values("as_of_at")
    right = pr[["purchased_at", "country", "product", "median"]].rename(columns={"product": "plan"})
    med = pd.merge_asof(left, right, left_on="as_of_at", right_on="purchased_at", by=["country", "plan"],
                        direction="backward").set_index("row")["median"].reindex(s.index)
    s["price_vs_country_median"] = s["renewal_price_usd"] / med
    # refunds the subscriber received before the snapshot
    refunds = t.loc[t["refunded_at"].notna(), ["user_id", "refunded_at"]].rename(columns={"refunded_at": "t"})
    s["prior_refunds"], _ = _events_up_to(s, refunds)


def _billing_counts(s: pd.DataFrame, tx: pd.DataFrame) -> np.ndarray:
    """Billing issues detected in (as_of_at - 30 days, as_of_at] for each snapshot's subscriber."""
    events = tx.loc[tx["billing_issue_detected_at"].notna(), ["user_id", "billing_issue_detected_at"]]
    if events.empty:
        return np.zeros(len(s))
    snap = s[["user_id", "as_of_at"]].reset_index().rename(columns={"index": "row"})
    m = snap.merge(events, on="user_id")
    hit = (m["billing_issue_detected_at"] <= m["as_of_at"]) & \
          (m["billing_issue_detected_at"] > m["as_of_at"] - pd.Timedelta(days=BILLING_LOOKBACK_DAYS))
    counts = m[hit].groupby("row").size()
    return counts.reindex(range(len(s)), fill_value=0).to_numpy(dtype=float)


def feature_record(row: pd.Series | dict, feature_set: str = "temporal") -> dict:
    """JSON-ready feature dict for the inference API (None for missing values)."""
    out = {}
    for f in FEATURE_SETS[feature_set]:
        v = row[f]
        if f in BOOLEAN:
            out[f] = bool(v)
        elif f in CATEGORICAL:
            out[f] = None if pd.isna(v) else str(v)
        else:
            out[f] = None if v is None or (isinstance(v, float) and np.isnan(v)) else float(v)
    return out
