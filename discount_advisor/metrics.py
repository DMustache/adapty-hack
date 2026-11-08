"""MEASURED baselines: conversion, renewal survival, refunds, revenue per payer, traffic.

Everything is computed from observed data, except the renewal-curve tail beyond the periods the data can
support. That tail is a rule (geometric extension), and its share of revenue is reported separately.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from data import CATALOG, CONVERSION_WINDOW_DAYS, SUBSCRIPTION_PRODUCTS, Dataset

MIN_AT_RISK = 30   # a renewal step is "observed" only if at least this many chains had a known outcome
MIN_PAYERS = 30    # audiences with fewer payers are flagged and get no recommendation
TAIL_RATES = 3     # tail retention = mean of the last 3 observed one-period renewal rates
DURATIONS = ("first_payment", "1m", "3m", "all")


def horizon_days(horizon_months: int) -> float:
    return horizon_months * 365 / 12


def periods_in_horizon(product: str, horizon_months: int) -> int:
    """Number of payments in [0, horizon): payment k (0-based) happens on day k * period."""
    days = CATALOG[product]["period_days"]
    if days is None:
        return 1  # lifetime: one payment
    return max(1, int(np.ceil(horizon_days(horizon_months) / days - 1e-9)))


@dataclass
class Survival:
    """s[k] = P(chain pays receipt k+1 | paid receipt 1), k = 0..n-1 within the horizon.

    Unit of analysis: one payment chain (user_id + originally_purchased_at). Discrete Kaplan-Meier over paid
    receipts; a chain whose current period is still open at the cutoff is censored at that step.
    """
    product: str
    s: np.ndarray
    observed_periods: int            # s[:observed_periods] is estimated from data (incl. s[0] = 1)
    tail_retention: float            # per-period retention used for s[observed_periods:]
    tail_identified: bool = True     # False if no renewal step had enough data to define a tail
    at_risk: list = field(default_factory=list)

    @property
    def extrapolated(self) -> bool:
        return self.observed_periods < len(self.s)


def renewal_survival(chains: pd.DataFrame, product: str, horizon_months: int) -> Survival:
    n_h = periods_in_horizon(product, horizon_months)
    c = chains[(chains["product"] == product) & chains.get("is_subscription", True)]
    s = np.ones(n_h)
    rates, at_risk_list, observed = [], [], 1
    for k in range(1, n_h):  # transition from paid receipt k to receipt k+1
        at_risk = int(((c["paid_periods"] >= k) & ~((c["paid_periods"] == k) & c["censored"])).sum())
        if at_risk < MIN_AT_RISK:
            break
        survived = int((c["paid_periods"] >= k + 1).sum())
        rates.append(survived / at_risk)
        at_risk_list.append(at_risk)
        s[k] = s[k - 1] * rates[-1]
        observed = k + 1
    identified = bool(rates) or n_h == 1
    tail = float(np.mean(rates[-TAIL_RATES:])) if rates else 0.0
    for k in range(observed, n_h):
        s[k] = s[k - 1] * tail
    return Survival(product, s, observed, tail, identified, at_risk_list)


def product_values(ds: Dataset, horizon_months: int) -> dict[str, Survival]:
    return {p: renewal_survival(ds.chains, p, horizon_months) for p in CATALOG}


def refund_rate(tx: pd.DataFrame) -> pd.Series:
    """Share of PAID receipts that were refunded, per product (trials excluded)."""
    paid = tx[tx["is_paid"]]
    return paid.groupby("product")["is_refunded"].mean().astype(float)


def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval for a proportion k / n."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (float(max(0.0, centre - half)), float(min(1.0, centre + half)))


def observed_weeks(ds: Dataset) -> float:
    return (ds.as_of - ds.users["install_at"].min()).total_seconds() / (7 * 86400)


@dataclass
class SegmentBaseline:
    name: str
    installs: int                  # mature installs (installed >= CONVERSION_WINDOW_DAYS before the cutoff)
    converters: int                # of those, paid within the conversion window
    conversion: float              # c0
    value_per_converter: float     # V0: expected net-of-refund USD per payer over the horizon, BEFORE store fee
    product_mix: pd.Series
    revenue_per_install: float     # c0 * V0
    conversion_ci: tuple = (0.0, 0.0)
    revenue_sd: float = 0.0        # std of expected horizon revenue per mature install (non-payers = 0)
    weekly_installs: float = 0.0   # ALL installs in the audience per observed week (eligible traffic)
    v0_split: dict = field(default_factory=dict)       # first receipt / estimated renewals / extrapolated tail
    observed_net_per_payer: float = 0.0                 # cash actually received so far (MEASURED, not a projection)
    refund_rate_receipts: float = 0.0                   # share of this audience's paid receipts refunded
    paid_receipts: int = 0
    v0_se: float = 0.0             # standard error of V0 across payers (sampling uncertainty)
    _weights: pd.DataFrame = None
    _survivals: dict = None

    @property
    def payers(self) -> int:
        return self.converters

    @property
    def small(self) -> bool:
        return self.converters < MIN_PAYERS

    def measured(self, duration: str):
        """Inputs for economics.simulate."""
        from economics import Measured
        return Measured(c0=self.conversion, v0=self.value_per_converter, a=self.affected_share(duration),
                        installs=self.installs, payers=self.converters, v0_se=self.v0_se)

    def affected_share(self, duration: str) -> float:
        """Share of V0 the discount touches, from this audience's plan mix and the selected horizon.

        duration: "first_payment" (the first PAID receipt; a free trial is not a receipt) | "1m" | "3m" |
                  "all" (every payment within the horizon = permanent price cut).
        """
        if duration not in DURATIONS:
            raise ValueError(duration)
        if self._weights is None or self._weights.empty:
            return 1.0
        touched = total = 0.0
        for product, w in self._weights.groupby("product")["w"]:
            s = self._survivals[product].s
            if duration == "first_payment":
                m = 1
            elif duration == "all":
                m = len(s)
            else:
                m = min(len(s), periods_in_horizon(product, int(duration.rstrip("m"))))
            touched += w.sum() * s[:m].sum()
            total += w.sum() * s.sum()
        return float(touched / total) if total else 1.0


def segment_baseline(ds: Dataset, mask: pd.Series, name: str, horizon_months: int,
                     survivals: dict[str, Survival] | None = None) -> SegmentBaseline:
    survivals = survivals or product_values(ds, horizon_months)
    refunds = refund_rate(ds.tx)
    u = ds.users[mask & ds.users["mature"]]
    conv = u[u["converted"]]
    keep = 1 - conv["product"].map(refunds).astype(float).fillna(0)
    first = (conv["first_price_usd"] * keep).astype(float)        # expected net value of one receipt
    s_sum = conv["product"].map(lambda p: survivals[p].s.sum()).astype(float)
    s_obs = conv["product"].map(lambda p: survivals[p].s[:survivals[p].observed_periods].sum()).astype(float)
    per_user = first * s_sum
    v0 = float(per_user.mean()) if len(conv) else 0.0
    c0 = len(conv) / len(u) if len(u) else 0.0
    tot = float(per_user.sum())
    split = {"first_receipt": float(first.sum() / tot) if tot else 1.0,
             "estimated_renewals": float((first * (s_obs - 1)).sum() / tot) if tot else 0.0,
             "extrapolated_tail": float((first * (s_sum - s_obs)).sum() / tot) if tot else 0.0}
    rev_all = np.zeros(len(u))
    rev_all[: len(conv)] = per_user.to_numpy()
    weeks = observed_weeks(ds)
    receipts = ds.tx[ds.tx["is_paid"] & ds.tx["user_id"].isin(u["user_id"])]
    return SegmentBaseline(
        name=name, installs=len(u), converters=len(conv), conversion=c0, value_per_converter=v0,
        product_mix=conv["product"].value_counts(normalize=True), revenue_per_install=c0 * v0,
        conversion_ci=wilson_ci(len(conv), len(u)),
        revenue_sd=float(rev_all.std(ddof=1)) if len(u) > 1 else 0.0,
        weekly_installs=int(mask.sum()) / weeks if weeks else 0.0,
        v0_split=split,
        observed_net_per_payer=float(conv["observed_net_usd"].mean()) if len(conv) else 0.0,
        refund_rate_receipts=float(receipts["is_refunded"].mean()) if len(receipts) else 0.0,
        paid_receipts=len(receipts),
        v0_se=float(per_user.std(ddof=1) / np.sqrt(len(conv))) if len(conv) > 1 else 0.0,
        _weights=pd.DataFrame({"product": conv["product"], "w": first}),
        _survivals=survivals,
    )


SEGMENT_DIMENSIONS = {
    "All users": None,
    "Placement": "placement",
    "Price tier": "price_tier",
    "Country": "country",
    "Platform": "platform",
    "Acquisition channel": "acquisition_channel",
    "Flow (paywall)": "flow",
}


def segment_table(ds: Dataset, dimension: str, horizon_months: int,
                  within: pd.Series | None = None) -> pd.DataFrame:
    """Measured baseline per segment value (optionally within an audience mask, e.g. one placement)."""
    survivals = product_values(ds, horizon_months)
    within = within if within is not None else pd.Series(True, index=ds.users.index)
    col = SEGMENT_DIMENSIONS[dimension]
    groups = [("All users", within)] if col is None else \
        [(str(v), within & (ds.users[col].astype(str) == str(v))) for v in sorted(ds.users[col].dropna().astype(str).unique())]
    rows = []
    for name, m in groups:
        if not m.any():
            continue
        b = segment_baseline(ds, m, name, horizon_months, survivals)
        lo, hi = b.conversion_ci
        rows.append({"segment": name, "installs": b.installs, "payers": b.converters, "conversion": b.conversion,
                     "conv_ci_low": lo, "conv_ci_high": hi, "refund_rate": b.refund_rate_receipts,
                     "observed_net_per_payer": b.observed_net_per_payer,
                     "value_per_converter": b.value_per_converter,
                     "extrapolated_share": b.v0_split.get("extrapolated_tail", 0.0),
                     "first_payment_share": b.affected_share("first_payment"),
                     "revenue_per_install": b.revenue_per_install, "weekly_installs": b.weekly_installs,
                     "small": b.small})
    return pd.DataFrame(rows).sort_values("revenue_per_install", ascending=False).reset_index(drop=True)


def country_price_vs_conversion(ds: Dataset) -> pd.DataFrame:
    """Observational: regional price index vs conversion per country. Confounded; NOT a price-response estimate."""
    u = ds.users[ds.users["mature"]]
    return (u.groupby("country")
            .agg(price_index=("price_index", "first"), conversion=("converted", "mean"), installs=("user_id", "size"))
            .reset_index().sort_values("price_index"))


