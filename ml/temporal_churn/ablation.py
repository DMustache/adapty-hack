"""Do the onboarding/engagement attributes help? Ablation on the temporal holdout.

    python -m ml.temporal_churn.ablation [--data-dir PATH]

For each model (static, temporal_behaviour, temporal) refit WITHOUT the four attributes
    ai_edits_first_day, photos_imported, onboarding_goal, push_opt_in
using the same hyperparameters as reports/evaluation.json, the same snapshots and the same untouched holdout,
and compare with the full model: Brier difference with a subscriber-clustered bootstrap 95% CI, PR-AUC difference.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from sklearn.metrics import average_precision_score, brier_score_loss

from ml.temporal_churn import snapshots as S
from ml.temporal_churn.train import REPORT_DIR, SEED, cluster_boot, fit, holdout, predict

ATTRIBUTES = ["ai_edits_first_day", "photos_imported", "onboarding_goal", "push_opt_in"]


def main(data_dir=None) -> dict:
    rng = np.random.default_rng(SEED)
    params = {n: r["params"] for n, r in json.loads((REPORT_DIR / "evaluation.json").read_text())["models"].items()}
    users, tx, cutoff = S.load(data_dir)
    train, test, _ = holdout(S.build_snapshots(users, tx, cutoff), cutoff)
    y, groups = test["churn"].to_numpy(), test["user_id"].to_numpy()
    out = {}
    for name, features in ((n, S.FEATURE_SETS[n]) for n in S.EVALUATED_MODELS):
        reduced = [f for f in features if f not in ATTRIBUTES]
        p_full = predict(fit(train, features, params[name]), test, features)
        p_red = predict(fit(train, reduced, params[name]), test, reduced)
        d, lo, hi = cluster_boot(y, p_red, p_full, groups, rng)      # positive = attributes help
        out[name] = {"brier_without": float(brier_score_loss(y, p_red)), "brier_with": float(brier_score_loss(y, p_full)),
                     "brier_gain": d, "ci95": [lo, hi],
                     "pr_auc_without": float(average_precision_score(y, p_red)),
                     "pr_auc_with": float(average_precision_score(y, p_full))}
    lines = ["# Ablation: onboarding / first-day attributes", "",
             f"Removed: {', '.join(ATTRIBUTES)}. Same hyperparameters, snapshots and temporal holdout. "
             "Brier gain = Brier(without) − Brier(with); positive means the attributes help "
             "(subscriber-clustered bootstrap 95% CI).", "",
             "| Model | Brier without → with | Brier gain (95% CI) | PR-AUC without → with |", "|---|---|---|---|"]
    for n, r in out.items():
        lines.append(f"| {n} | {r['brier_without']:.5f} → {r['brier_with']:.5f} | {r['brier_gain']:+.5f} "
                     f"({r['ci95'][0]:+.5f} to {r['ci95'][1]:+.5f}) | {r['pr_auc_without']:.3f} → {r['pr_auc_with']:.3f} |")
    (REPORT_DIR / "ablation.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (REPORT_DIR / "ablation.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir")
    for n, r in main(ap.parse_args().data_dir).items():
        print(f"{n:20s} Brier {r['brier_without']:.5f} -> {r['brier_with']:.5f} gain {r['brier_gain']:+.5f} "
              f"CI [{r['ci95'][0]:+.5f}, {r['ci95'][1]:+.5f}]  PR-AUC {r['pr_auc_without']:.3f} -> {r['pr_auc_with']:.3f}")
