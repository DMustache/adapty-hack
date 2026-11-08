"""Convert the offline CSVs (50,000 users) into the seeder's dataset format (lumen_dataset.json.gz, version 1).

The shipped JSON holds the first 5,000 of the same users. Times are seconds relative to a fixed reference
(2026-11-03 00:12:04 UTC, derived from the shipped file); timezone and currency come from the country (a 1:1 mapping
in the shipped file). `verify()` checks that converting the first 5,000 CSV users reproduces the shipped JSON.

Usage:  python build_seed_dataset.py [--users 50000] [--out path]
"""
from __future__ import annotations

import argparse
import gzip
import json
import math
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parent / "adapty-seed-data-hack"
OFFLINE = REPO / "data" / "offline"
SHIPPED = REPO / "data" / "lumen_dataset.json.gz"
DEFAULT_OUT = HERE / ".live_cache" / "lumen_dataset_50k.json.gz"
ATTRS = ["acquisition_channel", "onboarding_goal", "ai_edits_first_day", "photos_imported", "push_opt_in", "app_version"]


def _shipped() -> dict:
    with gzip.open(SHIPPED, "rt", encoding="utf-8") as f:
        return json.load(f)


def reference_time(shipped: dict, users: pd.DataFrame) -> pd.Timestamp:
    refs = {pd.Timestamp(r.install_at) - pd.Timedelta(seconds=x["install"])
            for r, x in zip(users.head(200).itertuples(), shipped["users"][:200])}
    if len(refs) != 1:
        raise ValueError(f"no single reference time: {refs}")
    return refs.pop()


def _clean(v):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    return v


def convert(n_users: int | None = None) -> dict:
    shipped = _shipped()
    users = pd.read_csv(OFFLINE / "users.csv.gz")
    tx = pd.read_csv(OFFLINE / "transactions.csv.gz")
    ref = reference_time(shipped, users)
    geo = {x["country"]: (x["timezone"], x["currency"]) for x in shipped["users"]}

    def off(ts):
        return None if pd.isna(ts) else int(round((pd.Timestamp(ts) - ref).total_seconds()))

    tx = tx.sort_values(["user_id", "seq"])
    by_user = {uid: g for uid, g in tx.groupby("user_id")}
    out = []
    for r in users.head(n_users).itertuples() if n_users else users.itertuples():
        i = int(r.user_id[1:])
        rows = []
        for t in (by_user.get(r.user_id, pd.DataFrame()).itertuples()):
            sub = t.purchase_type == "subscription"
            rows.append({
                "product": t.product, "t": off(t.purchased_at), "price": float(t.price_local), "usd": float(t.price_usd),
                "offer": _clean(t.offer), "refunded": off(t.refunded_at), "reason": _clean(t.cancellation_reason),
                "purchase_type": t.purchase_type, "exp": off(t.expires_at) if sub else None,
                "orig": off(t.originally_purchased_at) if sub else None,
                "renew": (str(t.renew_status) == "True") if sub else None,
                "renew_changed": off(t.renew_status_changed_at) if sub else None,
                "billing": off(t.billing_issue_detected_at) if sub else None,
            })
        tz, cur = geo[r.country]
        out.append({"i": i, "platform": r.platform, "country": r.country, "currency": cur, "locale": r.locale,
                    "timezone": tz, "device": r.device, "os": r.os, "install": off(r.install_at),
                    "attrs": {a: _clean(getattr(r, a)) for a in ATTRS}, "placement": r.placement, "flow": r.flow,
                    "ab_test": _clean(r.ab_test), "tx": rows})
    return {"version": 1, "app": "lumen", "days": shipped["days"], "users": out}


def _diff(a, b, path="") -> list[str]:
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for k in set(a) | set(b):
            out += _diff(a.get(k), b.get(k), f"{path}.{k}")
        return out
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return [f"{path}: len {len(a)} != {len(b)}"]
        return [d for x, y in zip(a, b) for d in _diff(x, y, path + "[]")]
    if isinstance(a, float) or isinstance(b, float):
        if a is None or b is None or abs(float(a) - float(b)) > 1e-6:
            return [f"{path}: {a!r} != {b!r}"]
        return []
    return [] if a == b else [f"{path}: {a!r} != {b!r}"]


def verify() -> list[str]:
    """Differences between the converted first 5,000 users and the shipped JSON (empty = identical)."""
    shipped = _shipped()
    mine = convert(len(shipped["users"]))
    diffs = []
    for a, b in zip(mine["users"], shipped["users"]):
        diffs += _diff(a, b, f"u{b['i']:05d}")
    return diffs


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--users", type=int, default=None)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--verify", action="store_true")
    args = ap.parse_args()
    if args.verify:
        d = verify()
        print(f"{len(d)} differences vs shipped dataset", *d[:20], sep="\n  ")
        raise SystemExit(1 if d else 0)
    data = convert(args.users)
    args.out.parent.mkdir(exist_ok=True)
    with gzip.open(args.out, "wt", encoding="utf-8") as f:
        json.dump(data, f)
    n_tx = sum(len(u["tx"]) for u in data["users"])
    print(f"wrote {len(data['users'])} users, {n_tx} transactions -> {args.out}")
