"""Round-2 candidate features: ablation + ranking among subscribers whose auto-renew is still ON.

    python -m ml.temporal_churn.ablation_round2 [--data-dir PATH]

Ablation (same rule as ablation_history.py, fixed before running): each group in snapshots.ROUND2_GROUPS, and all
of them together, is added to the deployed `temporal` feature set with the same CatBoost hyperparameters, snapshots
and temporal holdout. A group helps only if Brier is lower in every chronological CV fold inside the training period
AND the holdout Brier gain has a subscriber-clustered bootstrap 95% CI above 0.

Auto-renew-ON report: ranking quality on holdout snapshots where auto-renew is still on (the deployed model's main
signal, the switch-off, is absent there). Reported for the static, temporal_behaviour and deployed temporal models,
each candidate variant, and a model trained only on auto-renew-ON snapshots with all round-2 features.
"""
from __future__ import annotations

import argparse
import json

import numpy as np
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

from ml.temporal_churn import snapshots as S
from ml.temporal_churn.train import (REPORT_DIR, SEED, chrono_folds, cluster_boot, fit, holdout, predict,
                                     revenue_capture)


def cluster_auc_ci(y, p, groups, rng, n=500):
    ug, inv = np.unique(groups, return_inverse=True)
    rows = [np.where(inv == g)[0] for g in range(len(ug))]
    boots = []
    for _ in range(n):
        idx = np.concatenate([rows[i] for i in rng.integers(0, len(ug), len(ug))])
        if 0 < y[idx].mean() < 1:
            boots.append(roc_auc_score(y[idx], p[idx]))
    return float(np.quantile(boots, 0.025)), float(np.quantile(boots, 0.975))


def ranking(y, p, price, groups, rng) -> dict:
    lo, hi = cluster_auc_ci(y, p, groups, rng)
    return {"n": int(len(y)), "churn_rate": float(y.mean()), "roc_auc": float(roc_auc_score(y, p)),
            "roc_auc_ci95": [lo, hi], "pr_auc": float(average_precision_score(y, p)),
            "brier": float(brier_score_loss(y, p)), "brier_constant": float(brier_score_loss(y, np.full(len(y), y.mean()))),
            "rev_capture_10": revenue_capture(y, p, price, 0.10), "rev_capture_20": revenue_capture(y, p, price, 0.20)}


def main(data_dir=None) -> dict:
    rng = np.random.default_rng(SEED)
    params_all = {n: r["params"] for n, r in json.loads((REPORT_DIR / "evaluation.json").read_text())["models"].items()}
    params = params_all["temporal"]
    users, tx, cutoff = S.load(data_dir)
    snaps = S.build_snapshots(users, tx, cutoff)
    train, test, _ = holdout(snaps, cutoff)
    y, groups = test["churn"].to_numpy(), test["user_id"].to_numpy()
    folds = list(chrono_folds(train))
    base = S.FEATURE_SETS["temporal"]

    def evaluate(features, prm=params):
        fold_brier = []
        for trn, val in folds:
            p = predict(fit(train.iloc[trn], features, prm), train.iloc[val], features)
            fold_brier.append(float(brier_score_loss(train["churn"].iloc[val], p)))
        return fold_brier, predict(fit(train, features, prm), test, features)

    base_folds, p_base = evaluate(base)
    preds = {"temporal (deployed)": p_base}
    ablation = {"base": {"fold_brier": base_folds, "test_brier": float(brier_score_loss(y, p_base)),
                         "test_pr_auc": float(average_precision_score(y, p_base))}}
    candidates = {**S.ROUND2_GROUPS, "all_round2_features": S.ROUND2_FEATURES}
    for name, feats in candidates.items():
        folds_b, p = evaluate(base + feats)
        preds[f"temporal + {name}"] = p
        d, lo, hi = cluster_boot(y, p_base, p, groups, rng)
        wins = sum(b < a for a, b in zip(base_folds, folds_b))
        ablation[name] = {"features": feats, "varying_in_data": [f for f in feats if snaps[f].nunique(dropna=False) > 1],
                          "fold_brier": folds_b, "folds_improved": f"{wins}/{len(folds)}",
                          "test_brier": float(brier_score_loss(y, p)), "test_brier_gain": d, "ci95": [lo, hi],
                          "test_pr_auc": float(average_precision_score(y, p)), "helps": bool(wins == len(folds) and lo > 0)}
    for name in ("static", "temporal_behaviour"):
        f = S.FEATURE_SETS[name]
        preds[name] = predict(fit(train, f, params_all[name]), test, f)

    on = ~test["auto_renew_off"].to_numpy().astype(bool)
    tr_on = train[~train["auto_renew_off"].astype(bool)]
    f_on = S.FEATURE_SETS["temporal_round2"]
    preds["trained on auto-renew-ON only, all round-2 features"] = np.full(len(test), np.nan)
    preds["trained on auto-renew-ON only, all round-2 features"][on] = predict(fit(tr_on, f_on, params), test[on], f_on)
    price = test["renewal_price_usd"].to_numpy(float)
    on_report = {n: ranking(y[on], p[on], price[on], groups[on], rng) for n, p in preds.items()}
    out = {"ablation": ablation, "auto_renew_on": on_report,
           "already_in_deployed_model": ["placement", "flow", "acquisition_channel", "app_version"]}
    (REPORT_DIR / "ablation_round2.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    (REPORT_DIR / "ablation_round2.md").write_text(render(out), encoding="utf-8")
    return out


def render(o: dict) -> str:
    a, b = o["ablation"], o["ablation"]["base"]
    L = ["# Round-2 candidate features: ablation", "",
         "Each group is added to the deployed temporal model (same hyperparameters, snapshots, holdout). Helps = lower "
         "Brier in every chronological CV fold AND holdout gain with 95% CI above 0. `cancellation_reason` is never "
         "used. Already in the deployed model, so not re-added: " + ", ".join(o["already_in_deployed_model"]) + ".", "",
         f"Deployed temporal set: holdout Brier {b['test_brier']:.5f}, PR-AUC {b['test_pr_auc']:.3f}.", "",
         "| Group | Varies in this data | CV folds improved | Holdout Brier gain (95% CI) | PR-AUC | Helps |",
         "|---|---|---|---|---|---|"]
    for n, r in a.items():
        if n != "base":
            L.append(f"| {n} | {', '.join(r['varying_in_data']) or 'no (constant)'} | {r['folds_improved']} | "
                     f"{r['test_brier_gain']:+.5f} ({r['ci95'][0]:+.5f} to {r['ci95'][1]:+.5f}) | "
                     f"{r['test_pr_auc']:.3f} | {'yes' if r['helps'] else 'no'} |")
    first = next(iter(o["auto_renew_on"].values()))
    L += ["", "## Ranking among subscribers whose auto-renew is still ON", "",
          f"Holdout snapshots with auto-renew on: {first['n']:,}, churn {first['churn_rate']:.1%}. "
          "ROC-AUC 0.5 = random ranking.", "",
          "| Model | ROC-AUC (95% CI) | PR-AUC | Brier (constant) | Lost revenue in top 10% / 20% |", "|---|---|---|---|---|"]
    for n, r in o["auto_renew_on"].items():
        L.append(f"| {n} | {r['roc_auc']:.3f} ({r['roc_auc_ci95'][0]:.3f}–{r['roc_auc_ci95'][1]:.3f}) | "
                 f"{r['pr_auc']:.3f} | {r['brier']:.5f} ({r['brier_constant']:.5f}) | "
                 f"{r['rev_capture_10']:.1%} / {r['rev_capture_20']:.1%} |")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir")
    res = main(ap.parse_args().data_dir)
    print(open(REPORT_DIR / "ablation_round2.md", encoding="utf-8").read())
