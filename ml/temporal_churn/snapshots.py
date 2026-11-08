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

FEATURE_SETS = {
    # attributes known at sign-up only: one value per subscription period, whatever the date
    "static": STATIC_CATEGORICAL + STATIC_NUMERIC + STATIC_BOOLEAN,
    # + how far into the period, how long subscribed, renewal history, billing history (no auto-renew status)
    "temporal_behaviour": STATIC_CATEGORICAL + STATIC_NUMERIC + STATIC_BOOLEAN + TEMPORAL_NUMERIC,
    # + subscription status as of the snapshot (auto-renew switched off, and since when): the deployed model
    "temporal": STATIC_CATEGORICAL + STATIC_NUMERIC + STATIC_BOOLEAN + TEMPORAL_NUMERIC
                + STATUS_BOOLEAN + STATUS_NUMERIC,
}
CATEGORICAL = set(STATIC_CATEGORICAL)
BOOLEAN = set(STATIC_BOOLEAN + STATUS_BOOLEAN)


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
    resolved = s["renewal_due_at"] <= cutoff - pd.Timedelta(days=OUTCOME_MARGIN_DAYS)
    s["churn"] = np.where(resolved, (~s["renewed"]).astype(float), np.nan)
    keep = ["user_id", "seq", "as_of_at", "renewal_due_at", "churn"] + FEATURE_SETS["temporal"]
    return s[keep].sort_values(["as_of_at", "user_id"]).reset_index(drop=True)


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
