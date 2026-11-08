"""Summaries of the live Adapty apps, computed ONLY from local snapshots in .live_cache/ (no network).

Snapshots are written by adapty_live.py (seeded profiles) and adapty_live.snapshot_ids (simulated test users).
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from adapty_live import CACHE_DIR

APPS = {  # label -> (snapshot file, run id, historical users)
    "Lumen (5,000 users)": ("profiles_261329.json", "261329", 5000),
    "Lumen 50k (50,000 users)": ("profiles_247954.json", "247954", 50000),
}
EXPERIMENT_FILE = "experiment_700001.json"


def load_snapshot(name: str, cache_dir: Path = CACHE_DIR) -> dict | None:
    p = cache_dir / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def product_key(store_product_id: str | None) -> str | None:
    """'lumen.weekly' / 'lumen_weekly' / 'lumen.weekly_30off' -> 'weekly' / 'weekly' / 'weekly_30off'."""
    if not store_product_id:
        return None
    return store_product_id.split(":")[0].split(".", 1)[-1] if "." in store_product_id \
        else store_product_id.split(":")[0].split("_", 1)[-1]


def profiles_frame(snap: dict, run_id: str, n_users: int) -> pd.DataFrame:
    """One row per historical seeded user: offline user_id, buyer flag, product, cancellation reason, revenue."""
    rows = []
    for i in range(n_users):
        p = snap.get(f"lumen_{run_id}_{i:05d}")
        if p is None:
            rows.append({"user_id": f"u{i:05d}", "present": False})
            continue
        items = (p.get("subscriptions") or []) + (p.get("non_subscriptions") or [])
        it = items[0] if items else {}
        rows.append({"user_id": f"u{i:05d}", "present": True, "buyer": bool(items),
                     "product": product_key(it.get("store_product_id")), "reason": it.get("cancellation_reason"),
                     "revenue": float(p.get("total_revenue_usd") or 0)})
    return pd.DataFrame(rows).set_index("user_id")


def live_vs_offline(ds, snap: dict, run_id: str, n_users: int) -> pd.DataFrame:
    """Side-by-side figures for the same users: live Adapty vs the offline CSVs the advisor uses."""
    live = profiles_frame(snap, run_id, n_users)
    ids = live.index
    tx = ds.tx[ds.tx.user_id.isin(ids)].sort_values(["user_id", "seq"])
    last = tx.groupby("user_id").tail(1).set_index("user_id")
    first = tx.groupby("user_id").head(1).set_index("user_id")
    buyers_off = tx.user_id.nunique()
    lv = live[live.present]
    rows = [
        ("Users found", f"{int(live.present.sum()):,} / {len(live):,}", f"{len(live):,}"),
        ("Users with a purchase or trial", f"{int(lv.buyer.sum()):,}", f"{buyers_off:,}"),
        ("Last receipt refunded", f"{int((lv.reason == 'refund').sum()):,}", f"{int(last.refunded_at.notna().sum()):,}"),
        ("Voluntarily cancelled", f"{int((lv.reason == 'voluntarily_cancelled').sum()):,}",
         f"{int((last.cancellation_reason == 'voluntarily_cancelled').sum()):,}"),
        ("Billing error", f"{int((lv.reason == 'billing_error').sum()):,}",
         f"{int((last.cancellation_reason == 'billing_error').sum()):,}"),
        ("Revenue, USD (live: Adapty FX, net of refunds; offline: price_usd, net)",
         f"${lv.revenue.sum():,.0f}", f"${tx.price_usd.where(tx.refunded_at.isna(), 0).sum():,.0f}"),
    ]
    mix_live = lv.loc[lv.buyer.astype(bool), "product"].value_counts(normalize=True)
    mix_off = first["product"].value_counts(normalize=True)
    for p in sorted(set(mix_live.index) | set(mix_off.index)):
        rows.append((f"Plan mix: {p}", f"{mix_live.get(p, 0):.1%}", f"{mix_off.get(p, 0):.1%}"))
    return pd.DataFrame(rows, columns=["Measure", "Live Adapty", "Offline CSV"])


def experiment_results(snap: dict, specs: list[dict], run_id: str = "700001") -> pd.DataFrame:
    """Per arm of the SIMULATED discount test: users, buyers, conversion, Adapty revenue per user."""
    rows = []
    for spec in specs:
        p = snap.get(f"lumen_{run_id}_D{spec['k']:04d}")
        items = ((p or {}).get("subscriptions") or []) + ((p or {}).get("non_subscriptions") or [])
        rows.append({"arm": spec["arm"], "present": p is not None, "buyer": bool(items),
                     "discounted_product": any("30off" in (x.get("store_product_id") or "") for x in items),
                     "revenue": float((p or {}).get("total_revenue_usd") or 0)})
    df = pd.DataFrame(rows)
    out = df.groupby("arm").agg(users=("present", "sum"), buyers=("buyer", "sum"),
                                on_30off_product=("discounted_product", "sum"), revenue=("revenue", "sum"))
    out["conversion"] = out.buyers / out.users
    out["revenue_per_user"] = out.revenue / out.users
    return out.reindex(["control", "discount"])
