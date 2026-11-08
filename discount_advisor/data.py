"""Load and prepare the Adapty offline dataset (SYNTHETIC 'Lumen' app).

Only fields that exist in data/offline/*.csv.gz are used. Every derived column is documented here.

Data semantics established by inspection (and asserted in tests/test_data.py):
  * one row per install in users.csv; one row per receipt in transactions.csv, keyed by (user_id, seq)
  * every payer has at most ONE payment chain (one `originally_purchased_at`), receipts contiguous:
    seq 0, 1, 2, ... and each receipt starts exactly when the previous one expires; no re-subscriptions
  * free trials are always seq 0 with price 0 (weekly: 3 days, annual_trial: 7 days)
  * lifetime is a one-time purchase with no expiry; it is not a subscription chain
  * refunds only ever hit a user's last receipt
  * `expires_at` can lie in the future (up to a year after the data ends), so it is NOT an observation date
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

_HERE = Path(__file__).resolve().parent
_CANDIDATE_DIRS = [
    _HERE / "source" / "data" / "offline",
    _HERE.parent / "source" / "data" / "offline",
    _HERE.parent / "adapty-seed-data-hack" / "data" / "offline",
]


def default_data_dir() -> Path:
    """$DISCOUNT_DATA_DIR, else the first of source/data/offline or adapty-seed-data-hack/data/offline that exists."""
    env = os.environ.get("DISCOUNT_DATA_DIR")
    if env:
        return Path(env)
    for d in _CANDIDATE_DIRS:
        if (d / "users.csv.gz").exists():
            return d
    raise FileNotFoundError("users.csv.gz not found in: " + ", ".join(map(str, _CANDIDATE_DIRS)))


# Catalog list prices (USD, US tier) from seed_adapty.py. Period lengths are the ones observed in the data
# (paid receipts: weekly 7.0 d, monthly 30.0 d, annual 365.0 d). None = lifetime (no renewal).
CATALOG = {
    "weekly": {"list_usd": 6.99, "period_days": 7, "trial_days": 3},
    "monthly": {"list_usd": 12.99, "period_days": 30, "trial_days": 0},
    "annual": {"list_usd": 49.99, "period_days": 365, "trial_days": 0},
    "annual_trial": {"list_usd": 49.99, "period_days": 365, "trial_days": 7},
    "lifetime": {"list_usd": 99.99, "period_days": None, "trial_days": 0},
    "pro_annual": {"list_usd": 89.99, "period_days": 365, "trial_days": 0},
}
SUBSCRIPTION_PRODUCTS = [p for p, c in CATALOG.items() if c["period_days"]]

# Conversion = first PAID receipt within this many days of install. Rationale: in the data the first transaction
# happens <= 6 days after install and the longest trial is 7 days, so 13 days is the latest possible first payment
# (the observed maximum is 9.0 days). Only installs at least this old at the cutoff are "mature" and used as the
# conversion denominator, so every install in the cohort had the same chance to convert.
CONVERSION_WINDOW_DAYS = 14


@dataclass
class Dataset:
    users: pd.DataFrame          # one row per install + converter flags
    tx: pd.DataFrame             # one row per receipt + user attributes
    chains: pd.DataFrame         # one row per payer (chain): product, prices, paid periods, censoring
    as_of: pd.Timestamp          # observation cutoff: last observed event (never a future expires_at)
    data_dir: Path

    @property
    def data_end(self) -> pd.Timestamp:  # backwards-compatible alias
        return self.as_of


def _ts(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, utc=True, errors="coerce")


def observation_cutoff(users: pd.DataFrame, tx: pd.DataFrame) -> pd.Timestamp:
    """Latest timestamp of an event that has actually happened: install, purchase, renewal-status change,
    billing issue or refund. `expires_at` is a scheduled date and is deliberately excluded."""
    return max(users["install_at"].max(), tx["purchased_at"].max(), tx["renew_status_changed_at"].max(),
               tx["billing_issue_detected_at"].max(), tx["refunded_at"].max())


def load(data_dir: Path | str | None = None) -> Dataset:
    data_dir = Path(data_dir) if data_dir else default_data_dir()
    users = pd.read_csv(data_dir / "users.csv.gz")
    tx = pd.read_csv(data_dir / "transactions.csv.gz")

    users["install_at"] = _ts(users["install_at"])
    for c in ["purchased_at", "expires_at", "originally_purchased_at", "renew_status_changed_at",
              "billing_issue_detected_at", "refunded_at"]:
        tx[c] = _ts(tx[c])
    as_of = observation_cutoff(users, tx)

    # Regional price index = what the country pays for annual vs the US list price (observed).
    annual = tx[(tx["product"] == "annual") & (tx["price_usd"] > 0)]
    country_of = users.set_index("user_id")["country"]
    idx = (annual.assign(country=annual["user_id"].map(country_of))
           .groupby("country")["price_usd"].median() / CATALOG["annual"]["list_usd"]).round(2)
    users["price_index"] = users["country"].map(idx)
    users["price_tier"] = pd.cut(users["price_index"], bins=[0, 0.5, 0.75, 0.95, 1.01],
                                 labels=["Tier C (<=50%)", "Tier B (55-70%)", "Tier A- (80-90%)", "Tier A (100%)"]
                                 ).astype(str)

    tx = tx.merge(users[["user_id", "country", "platform", "acquisition_channel", "placement", "flow",
                         "price_tier"]], on="user_id", how="left")
    tx["is_paid"] = tx["price_usd"] > 0          # a free trial is NOT a paid receipt
    tx["is_refunded"] = tx["refunded_at"].notna()
    tx["net_usd"] = tx["price_usd"].where(~tx["is_refunded"], 0.0)  # refunded receipt contributes 0

    chains = _build_chains(tx, as_of)
    users = users.merge(chains[["user_id", "product", "first_price_usd", "first_paid_at", "observed_net_usd"]],
                        on="user_id", how="left")
    users["days_to_first_paid"] = (users["first_paid_at"] - users["install_at"]).dt.total_seconds() / 86400
    users["mature"] = users["install_at"] <= as_of - pd.Timedelta(days=CONVERSION_WINDOW_DAYS)
    # Converted = paid within the window. A later refund does NOT undo the conversion (it only zeroes that receipt).
    users["converted"] = users["days_to_first_paid"].le(CONVERSION_WINDOW_DAYS).fillna(False).astype(bool)
    return Dataset(users=users, tx=tx, chains=chains, as_of=as_of, data_dir=data_dir)


def _build_chains(tx: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
    """One row per payer = one payment chain (the data has at most one chain per user; asserted in tests).

    paid_periods: number of paid receipts (trial excluded).
    censored: the last paid period had not ended by the cutoff (expires_at > as_of) and was not refunded,
              so whether it renews is unknown. Users who switched auto-renew off are censored too: they could
              switch it back on, and treating them as churned while auto-renewers stay "unknown" would bias the
              renewal estimate downwards. A refund ends the entitlement on an observed date, so it is an event.
    """
    paid = tx[tx["is_paid"]].sort_values(["user_id", "seq"])
    g = paid.groupby("user_id")
    last = g.tail(1).set_index("user_id")
    out = pd.DataFrame({
        "chain_id": g["originally_purchased_at"].first().astype(str),
        "product": g["product"].first(),
        "is_subscription": g["purchase_type"].first().eq("subscription"),
        "first_price_usd": g["price_usd"].first(),
        "first_paid_at": g["purchased_at"].first(),
        "paid_periods": g.size(),
        "refunded_payments": g["is_refunded"].sum(),
        "observed_net_usd": g["net_usd"].sum(),
    })
    open_period = (last["expires_at"] > as_of) & last["refunded_at"].isna()
    out["censored"] = (out["is_subscription"] & open_period.reindex(out.index).fillna(False)).astype(bool)
    return out.reset_index()
