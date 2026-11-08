#!/usr/bin/env python3
"""Replay point-in-time snapshots through the inference API to build per-subscriber churn-risk trajectories.

Sends one POST /v1/predict per snapshot (as_of_at, renewal_due_at, renewal_price_usd + features); the inference
service forwards each result to analytics, which stores it as a new row. Local services only: no Adapty calls.

Usage:
  python scripts/score_temporal_snapshots.py --data-dir PATH [--subscribers 50] [--days 35]
         [--inference-url http://127.0.0.1:8001] [--dry-run out.jsonl]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

from ml.temporal_churn import snapshots as S  # noqa: E402

MODEL_ID = "lumen-temporal-catboost"
APP_ID = "lumen"


def build_requests(snaps: pd.DataFrame, subscribers: int, days: int) -> list[dict]:
    start = snaps["as_of_at"].max() - pd.Timedelta(days=days)
    recent = snaps[snaps["as_of_at"] >= start]
    # subscribers with the longest recent history, deterministic order
    chosen = (recent.groupby("user_id").size().sort_values(ascending=False, kind="stable")
              .head(subscribers).index)
    rows = recent[recent["user_id"].isin(chosen)].sort_values(["user_id", "as_of_at"])
    out = []
    for r in rows.itertuples(index=False):
        rec = r._asdict()
        days_left = (r.renewal_due_at - r.as_of_at).total_seconds() / 86400
        if days_left <= 0 or r.plan not in ("weekly", "monthly"):
            continue
        # These are synthetic offline IDs. Keep their original values out of service and dashboard records.
        pseudonym = hashlib.sha256(f"lumen-synthetic:{r.user_id}".encode()).hexdigest()[:24]
        cutoff = r.as_of_at.isoformat().replace("+00:00", "Z")
        due = r.renewal_due_at.isoformat().replace("+00:00", "Z")
        out.append({
            "request_id": f"temporal-{pseudonym}-{r.as_of_at:%Y%m%dT%H%M%S}",
            "app_id": APP_ID, "user_id": pseudonym, "model_id": MODEL_ID,
            "renewal_horizon_days": max(1, min(365, math.ceil(days_left))),
            "context": {"as_of_at": cutoff, "renewal_due_at": due,
                        "feature_source_ref": "synthetic-offline-replay"},
            "features": S.feature_record(rec, "temporal"),
        })
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir")
    ap.add_argument("--subscribers", type=int, default=50)
    ap.add_argument("--days", type=int, default=35, help="score snapshots from the last N days of data")
    ap.add_argument("--inference-url", default="http://127.0.0.1:8001")
    ap.add_argument("--dry-run", metavar="OUT.jsonl", help="write the requests to a file instead of sending them")
    args = ap.parse_args()
    users, tx, cutoff = S.load(args.data_dir)
    snaps = S.build_snapshots(users, tx, cutoff)
    requests = build_requests(snaps, args.subscribers, args.days)
    print(f"{len(requests)} snapshots for {len({r['user_id'] for r in requests})} subscribers")
    if args.dry_run:
        Path(args.dry_run).write_text("\n".join(json.dumps(r) for r in requests) + "\n", encoding="utf-8")
        print(f"wrote {args.dry_run}")
        return
    import httpx
    ok = failed = 0
    with httpx.Client(base_url=args.inference_url, timeout=30) as client:
        for r in requests:
            res = client.post("/v1/predict", json=r)
            if res.status_code == 200:
                ok += 1
            else:
                failed += 1
                if failed <= 5:
                    print(f"  {r['request_id']}: HTTP {res.status_code} {res.text[:200]}")
    print(f"stored {ok}, failed {failed}")


if __name__ == "__main__":
    main()
