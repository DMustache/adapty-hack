"""Evaluation by days before renewal, with subscriber-clustered bootstrap confidence intervals.

Buckets (days_until_renewal = renewal_due_at - as_of_at): 30+, 15-30, 7-14, 1-6.
Metrics: ROC-AUC, PR-AUC, share of actually lost renewal revenue in the top 10% ranked by expected revenue at risk
(probability x renewal price). CIs resample subscribers (a subscriber has many snapshots), not rows.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score

BUCKETS = [("30+", 30.0, np.inf), ("15–30", 15.0, 30.0), ("7–14", 7.0, 15.0), ("1–6", 1.0, 7.0)]
N_BOOT = 500


def bucket_of(days: pd.Series) -> pd.Series:
    out = pd.Series(pd.NA, index=days.index, dtype="object")
    for name, lo, hi in BUCKETS:
        out[(days >= lo) & (days < hi)] = name
    return out


def top10_capture(y: np.ndarray, p: np.ndarray, price: np.ndarray) -> float:
    lost = y * price
    if lost.sum() == 0:
        return float("nan")
    k = max(1, int(round(0.1 * len(y))))
    top = np.argsort(-(p * price), kind="stable")[:k]
    return float(lost[top].sum() / lost.sum())


METRICS = {
    "roc_auc": lambda y, p, w: roc_auc_score(y, p),
    "pr_auc": lambda y, p, w: average_precision_score(y, p),
    "lost_revenue_top10": top10_capture,
}


def evaluate(y: np.ndarray, p: np.ndarray, price: np.ndarray, groups: np.ndarray, rng) -> dict:
    out = {"n": int(len(y)), "subscribers": int(len(np.unique(groups))), "churned": int(y.sum()),
           "churn_rate": float(y.mean()) if len(y) else float("nan")}
    if len(y) == 0 or y.min() == y.max():
        out["note"] = "not evaluable: no churn or no renewal in this bucket"
        return out
    ug, inv = np.unique(groups, return_inverse=True)
    members = [np.where(inv == g)[0] for g in range(len(ug))]
    boots = {m: [] for m in METRICS}
    for _ in range(N_BOOT):
        idx = np.concatenate([members[i] for i in rng.integers(0, len(ug), len(ug))])
        if y[idx].min() == y[idx].max():
            continue
        for m, fn in METRICS.items():
            boots[m].append(fn(y[idx], p[idx], price[idx]))
    for m, fn in METRICS.items():
        out[m] = float(fn(y, p, price))
        vals = np.array([v for v in boots[m] if v == v])
        out[f"{m}_ci95"] = [float(np.quantile(vals, 0.025)), float(np.quantile(vals, 0.975))] if len(vals) else None
    return out


def by_bucket(df: pd.DataFrame, p: np.ndarray, rng) -> dict:
    """df needs churn, days_until_renewal, renewal_price_usd, user_id; p aligned with df."""
    b = bucket_of(df["days_until_renewal"])
    out = {}
    for name, _, _ in BUCKETS + [("all", None, None)]:
        m = np.ones(len(df), bool) if name == "all" else (b == name).to_numpy()
        out[name] = evaluate(df["churn"].to_numpy()[m], p[m], df["renewal_price_usd"].to_numpy(float)[m],
                             df["user_id"].to_numpy()[m], rng)
    return out


def fmt(r: dict) -> str:
    """One markdown row of metrics with CIs."""
    if r["n"] == 0:
        return "0 | 0 | — | — | — | — |"
    if "note" in r:
        return f"{r['n']:,} | {r.get('churned', 0):,} | {r['churn_rate']:.1%} | — | — | — |"

    def ci(m, pct=False):
        lo, hi = r[f"{m}_ci95"] or (float("nan"), float("nan"))
        f = (lambda v: f"{v:.1%}") if pct else (lambda v: f"{v:.3f}")
        return f"{f(r[m])} ({f(lo)}–{f(hi)})"
    return (f"{r['n']:,} | {r['churned']:,} | {r['churn_rate']:.1%} | {ci('roc_auc')} | {ci('pr_auc')} | "
            f"{ci('lost_revenue_top10', pct=True)} |")
