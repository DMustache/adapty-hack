"""REAL evaluation of the deployed model by days before renewal, on snapshots where auto-renew is still ON.

    python -m ml.temporal_churn.eval_on_by_horizon [--data-dir PATH]

Uses the deployed artifact through the inference adapter (checksum-verified), on the untouched temporal holdout.
Buckets: 30+, 15-30, 7-14, 1-6 days before renewal. Metrics: ROC-AUC, PR-AUC, lost revenue in the top 10%, each
with a subscriber-clustered bootstrap 95% CI.
"""
from __future__ import annotations

import argparse
import json

import numpy as np

from ml.temporal_churn import horizon_eval as H
from ml.temporal_churn import snapshots as S
from ml.temporal_churn.train import REPORT_DIR, SEED, holdout
from services.inference.app.adapters.temporal_catboost import TemporalCatBoostAdapter


def main(data_dir=None) -> dict:
    rng = np.random.default_rng(SEED)
    adapter = TemporalCatBoostAdapter()
    adapter.load()
    users, tx, cutoff = S.load(data_dir)
    _, test, test_start = holdout(S.build_snapshots(users, tx, cutoff), cutoff)
    on = test[~test["auto_renew_off"].astype(bool)].reset_index(drop=True)
    p = np.array(adapter.predict_batch([S.feature_record(r, "temporal") for _, r in on.iterrows()]))
    res = H.by_bucket(on, p, rng)
    out = {"model": f"{adapter.model_id} {adapter.model_version} (sha256 {adapter.metadata['sha256'][:12]}…)",
           "holdout_from": test_start.isoformat(), "snapshots_auto_renew_on": int(len(on)), "by_bucket": res}
    (REPORT_DIR / "eval_auto_renew_on_by_horizon.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    L = ["# Deployed model on auto-renew-ON snapshots, by days before renewal (REAL evaluation)", "",
         f"Model {out['model']}, untouched holdout from {test_start:%d %b %Y}, {len(on):,} snapshots where auto-renew "
         "is still on. 95% CIs: subscriber-clustered bootstrap. ROC-AUC 0.5 = random; lost revenue in the top 10% "
         "≈ 10% for a random ranking.", "",
         "| Days before renewal | Snapshots | Churned | Churn rate | ROC-AUC (95% CI) | PR-AUC (95% CI) | "
         "Lost revenue in top 10% (95% CI) |", "|---|---|---|---|---|---|---|"]
    for name, r in res.items():
        L.append(f"| {name} | " + H.fmt(r))
    if res["30+"]["n"] == 0:
        L += ["", "**30+ is empty by construction**: only the first day of a monthly period is 30+ days before its "
              "renewal, and a monthly period starting inside the 28-day holdout cannot have its renewal resolved "
              "before the data ends, so those snapshots are censored (excluded), not missing."]
    (REPORT_DIR / "eval_auto_renew_on_by_horizon.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir")
    main(ap.parse_args().data_dir)
    print((REPORT_DIR / "eval_auto_renew_on_by_horizon.md").read_text(encoding="utf-8"))
