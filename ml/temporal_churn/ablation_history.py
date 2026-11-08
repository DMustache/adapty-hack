"""Which subscription-history features help the deployed temporal model?

    python -m ml.temporal_churn.ablation_history [--data-dir PATH]

For each group in snapshots.HISTORY_GROUPS (and all groups together), add it to the deployed `temporal` feature set
and compare with the deployed set, using the same CatBoost hyperparameters, snapshots and temporal holdout.
A group "helps" only if BOTH hold (rule fixed before running):
  * lower Brier in every chronological CV fold inside the training period (purged, as in train.py), and
  * Brier improvement on the untouched holdout with a subscriber-clustered bootstrap 95% CI above 0.
Groups with no variation in the data are reported as such (CatBoost cannot use a constant column).
"""
from __future__ import annotations

import argparse
import json

import numpy as np
from sklearn.metrics import average_precision_score, brier_score_loss

from ml.temporal_churn import snapshots as S
from ml.temporal_churn.train import REPORT_DIR, SEED, chrono_folds, cluster_boot, fit, holdout, predict


def main(data_dir=None) -> dict:
    rng = np.random.default_rng(SEED)
    params = json.loads((REPORT_DIR / "evaluation.json").read_text())["models"]["temporal"]["params"]
    users, tx, cutoff = S.load(data_dir)
    snaps = S.build_snapshots(users, tx, cutoff)
    train, test, _ = holdout(snaps, cutoff)
    y, groups = test["churn"].to_numpy(), test["user_id"].to_numpy()
    base = S.FEATURE_SETS["temporal"]
    folds = list(chrono_folds(train))

    def evaluate(features):
        fold_brier = []
        for trn, val in folds:
            p = predict(fit(train.iloc[trn], features, params), train.iloc[val], features)
            fold_brier.append(float(brier_score_loss(train["churn"].iloc[val], p)))
        return fold_brier, predict(fit(train, features, params), test, features)

    base_folds, p_base = evaluate(base)
    candidates = {**S.HISTORY_GROUPS, "all_history_features": S.HISTORY_FEATURES}
    out = {"base": {"features": "deployed temporal set", "fold_brier": base_folds,
                    "test_brier": float(brier_score_loss(y, p_base)),
                    "test_pr_auc": float(average_precision_score(y, p_base))}}
    for name, feats in candidates.items():
        varying = [f for f in feats if snaps[f].nunique(dropna=False) > 1]
        folds_b, p = evaluate(base + feats)
        d, lo, hi = cluster_boot(y, p_base, p, groups, rng)      # positive = adding the group helps
        wins = sum(b < a for a, b in zip(base_folds, folds_b))
        out[name] = {"features": feats, "varying_in_data": varying, "fold_brier": folds_b,
                     "folds_improved": f"{wins}/{len(folds)}", "test_brier": float(brier_score_loss(y, p)),
                     "test_brier_gain": d, "ci95": [lo, hi], "test_pr_auc": float(average_precision_score(y, p)),
                     "helps": bool(wins == len(folds) and lo > 0)}
    (REPORT_DIR / "ablation_history.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    (REPORT_DIR / "ablation_history.md").write_text(render(out), encoding="utf-8")
    return out


def render(o: dict) -> str:
    b = o["base"]
    L = ["# Subscription-history features: ablation", "",
         "Each group is added to the deployed temporal model (same hyperparameters, snapshots, holdout). "
         "Helps = lower Brier in every chronological CV fold AND holdout gain with 95% CI above 0. "
         "`cancellation_reason` is never used.", "",
         f"Deployed temporal set: holdout Brier {b['test_brier']:.5f}, PR-AUC {b['test_pr_auc']:.3f}.", "",
         "| Group | Varies in this data | CV folds improved | Holdout Brier gain (95% CI) | PR-AUC | Helps |",
         "|---|---|---|---|---|---|"]
    for n, r in o.items():
        if n == "base":
            continue
        vary = ", ".join(r["varying_in_data"]) or "no (constant)"
        L.append(f"| {n} | {vary} | {r['folds_improved']} | {r['test_brier_gain']:+.5f} "
                 f"({r['ci95'][0]:+.5f} to {r['ci95'][1]:+.5f}) | {r['test_pr_auc']:.3f} | "
                 f"{'yes' if r['helps'] else 'no'} |")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir")
    res = main(ap.parse_args().data_dir)
    print(f"base Brier {res['base']['test_brier']:.5f} folds {[round(x, 5) for x in res['base']['fold_brier']]}")
    for n, r in res.items():
        if n != "base":
            print(f"{n:38s} varies={r['varying_in_data']} folds {r['folds_improved']} gain {r['test_brier_gain']:+.5f} "
                  f"CI [{r['ci95'][0]:+.5f}, {r['ci95'][1]:+.5f}] PR-AUC {r['test_pr_auc']:.3f} helps={r['helps']}")
