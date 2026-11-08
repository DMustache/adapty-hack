"""Recalibrate the deployed temporal model on recent outcomes and report predicted vs actual churn rates.

    python -m ml.temporal_churn.recalibrate [--data-dir PATH]

Design (fixed before looking at results):
  * Calibration window: snapshots with as_of_at in the CALIB_DAYS before the holdout starts AND whose renewal was
    resolved before the holdout starts (no holdout outcome is used).
  * Out-of-time predictions for the window come from a copy of the model trained only on renewals resolved before
    the window starts (the deployed model saw the window during training, so its predictions there are optimistic).
  * Method: Platt recalibration, logit(p') = a + b * logit(p), fitted on the window. Intercept-only and isotonic are
    reported as sensitivity checks only.
  * Deployment: only with --deploy AND only if Platt beats the uncorrected model on the holdout in Brier, ECE and
    |mean predicted - actual| (verdict printed in the report). It then writes calibration.json (+ .sha256) next to
    the unchanged CatBoost artifact. The first run (2026-11-08) failed this check, so nothing is deployed.
  * Report: before/after on the untouched holdout (overall rate, by plan, by days until renewal, by channel /
    country / paywall; Brier, log loss, ECE, calibration slope/intercept, calibration table).
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, log_loss, roc_auc_score

from ml.temporal_churn import snapshots as S
from ml.temporal_churn.train import (ARTIFACT_DIR, EPS, REPORT_DIR, calib_slope_intercept, calibration, ece, fit,
                                     holdout, predict)

CALIB_DAYS = 21
CALIBRATED_VERSION = "1.1.0"


def logit(p):
    p = np.clip(p, EPS, 1 - EPS)
    return np.log(p / (1 - p))


def platt(p, a, b):
    return 1 / (1 + np.exp(-(a + b * logit(p))))


def group_rates(df: pd.DataFrame, cols: dict[str, np.ndarray], by: str) -> list[dict]:
    out = []
    for key, g in df.groupby(by):
        row = {by: str(key), "n": int(len(g)), "actual": float(g["churn"].mean())}
        for name in cols:
            row[name] = float(g[name].mean())
        out.append(row)
    return out


def summary(y, p) -> dict:
    slope, intercept = calib_slope_intercept(y, p)
    return {"mean_predicted": float(p.mean()), "actual": float(y.mean()), "brier": float(brier_score_loss(y, p)),
            "log_loss": float(log_loss(y, p)), "ece": ece(y, p), "calib_slope": slope, "calib_intercept": intercept,
            "roc_auc": float(roc_auc_score(y, p)), "pr_auc": float(average_precision_score(y, p)),
            "calibration": calibration(y, p)}


def main(data_dir=None, deploy: bool = False) -> dict:
    meta = json.loads((ARTIFACT_DIR / "metadata.json").read_text(encoding="utf-8"))
    params, features = meta["params"], meta["features"]
    users, tx, cutoff = S.load(data_dir)
    snaps = S.build_snapshots(users, tx, cutoff)
    train, test, test_start = holdout(snaps, cutoff)
    calib_start = test_start - pd.Timedelta(days=CALIB_DAYS)
    calib = train[train["as_of_at"] >= calib_start]
    early = train[train["renewal_due_at"] < calib_start]
    y_cal, y = calib["churn"].to_numpy(), test["churn"].to_numpy()

    p_cal = predict(fit(early, features, params), calib, features)        # out-of-time on the window
    lr = LogisticRegression(C=1e6, max_iter=1000).fit(logit(p_cal).reshape(-1, 1), y_cal)
    a, b = float(lr.intercept_[0]), float(lr.coef_[0][0])
    shift = float(logit(np.array([y_cal.mean()]))[0] - logit(np.array([p_cal.mean()]))[0])   # sensitivity only
    iso = IsotonicRegression(out_of_bounds="clip", y_min=EPS, y_max=1 - EPS).fit(p_cal, y_cal)

    deployed = predict(fit(train, features, params), test, features)       # = the deployed artifact's predictions
    variants = {"before (deployed v1.0.0)": deployed, "after: Platt": platt(deployed, a, b),
                "sensitivity: intercept shift": platt(deployed, shift, 1.0),
                "sensitivity: isotonic": np.clip(iso.predict(deployed), EPS, 1 - EPS)}
    t = test.assign(**{k: v for k, v in variants.items()})
    t["days_bucket"] = pd.cut(t["days_until_renewal"], [0, 1, 2, 3, 5, 8, 31], include_lowest=True).astype(str)
    out = {"calibration_window": {"from": calib_start.isoformat(), "to": test_start.isoformat(),
                                  "snapshots": int(len(calib)), "actual_churn": float(y_cal.mean()),
                                  "out_of_time_mean_predicted": float(p_cal.mean()),
                                  "early_model_rows": int(len(early))},
           "platt": {"a": a, "b": b}, "intercept_shift": shift,
           "holdout": {k: summary(y, v) for k, v in variants.items()},
           "by_group": {by: group_rates(t, variants, by)
                        for by in ("plan", "days_bucket", "acquisition_channel", "country", "flow")}}
    for by, rows in out["by_group"].items():
        out.setdefault("group_mae", {})[by] = {k: float(np.mean([abs(r[k] - r["actual"]) for r in rows]))
                                               for k in variants}

    before, after = out["holdout"]["before (deployed v1.0.0)"], out["holdout"]["after: Platt"]
    improves = (after["brier"] < before["brier"] and after["ece"] < before["ece"]
                and abs(after["mean_predicted"] - after["actual"]) < abs(before["mean_predicted"] - before["actual"]))
    out["verdict"] = {"platt_improves": bool(improves), "deployed": bool(deploy and improves)}
    (REPORT_DIR / "recalibration.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    (REPORT_DIR / "recalibration.md").write_text(render(out), encoding="utf-8")
    if not (deploy and improves):
        return out
    cal = {"method": "platt", "a": a, "b": b, "applies_to_model_sha256": meta["sha256"],
           "fitted_on": out["calibration_window"],
           "fitted_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat()}
    path = ARTIFACT_DIR / "calibration.json"
    path.write_text(json.dumps(cal, indent=1), encoding="utf-8")
    (ARTIFACT_DIR / "calibration.json.sha256").write_text(
        hashlib.sha256(path.read_bytes()).hexdigest() + "  calibration.json\n", encoding="utf-8")
    meta["model_version"] = CALIBRATED_VERSION
    meta["calibration"] = {"file": "calibration.json", "method": "platt"}
    meta["metrics_calibrated"] = {k: v for k, v in out["holdout"]["after: Platt"].items()
                                  if k != "calibration"}
    (ARTIFACT_DIR / "metadata.json").write_text(json.dumps(meta, indent=1, default=str), encoding="utf-8")
    return out


def render(o: dict) -> str:
    w = o["calibration_window"]
    L = ["# Recalibration: predicted vs actual churn rate", "",
         f"Calibration window: as-of {w['from'][:10]} – {w['to'][:10]}, {w['snapshots']:,} snapshots with renewals "
         f"resolved before the holdout (actual churn {w['actual_churn']:.1%}; the out-of-time model predicted "
         f"{w['out_of_time_mean_predicted']:.1%}). Platt: logit(p') = {o['platt']['a']:+.3f} + "
         f"{o['platt']['b']:.3f} · logit(p). Evaluated on the untouched holdout.", "",
         f"**Verdict:** Platt {'improves' if o['verdict']['platt_improves'] else 'does NOT improve'} Brier, ECE and "
         f"the overall rate on the holdout → {'deployed' if o['verdict']['deployed'] else 'not deployed'}.", "",
         "| Variant | Mean predicted | Actual | Brier | Log loss | ECE | Calib. slope / int. | ROC-AUC | PR-AUC |",
         "|---|---|---|---|---|---|---|---|---|"]
    for k, s in o["holdout"].items():
        L.append(f"| {k} | {s['mean_predicted']:.1%} | {s['actual']:.1%} | {s['brier']:.4f} | {s['log_loss']:.4f} | "
                 f"{s['ece']:.4f} | {s['calib_slope']:.2f} / {s['calib_intercept']:+.2f} | {s['roc_auc']:.3f} | "
                 f"{s['pr_auc']:.3f} |")
    keys = list(o["holdout"])
    L += ["", "Mean absolute error of group churn rates (predicted vs actual), by grouping:", "",
          "| Grouping | " + " | ".join(keys) + " |", "|---|" + "---|" * len(keys)]
    for by, m in o["group_mae"].items():
        L.append(f"| {by} | " + " | ".join(f"{m[k]:.2%}" for k in keys) + " |")
    for by in ("plan", "days_bucket"):
        L += ["", f"By {by}:", "", f"| {by} | n | Actual | Before | After (Platt) |", "|---|---|---|---|---|"]
        for r in o["by_group"][by]:
            L.append(f"| {r[by]} | {r['n']:,} | {r['actual']:.1%} | {r[keys[0]]:.1%} | {r[keys[1]]:.1%} |")
    L += ["", "Calibration table (deciles of predicted risk):", "",
          "| Decile | Before: predicted / observed | After: predicted / observed |", "|---|---|---|"]
    for cb, ca in zip(o["holdout"][keys[0]]["calibration"], o["holdout"][keys[1]]["calibration"]):
        L.append(f"| {cb['bin']} | {cb['mean_predicted']:.3f} / {cb['observed']:.3f} | "
                 f"{ca['mean_predicted']:.3f} / {ca['observed']:.3f} |")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir")
    ap.add_argument("--deploy", action="store_true", help="write calibration.json if Platt passes the check")
    args = ap.parse_args()
    main(args.data_dir, deploy=args.deploy)
    print(open(REPORT_DIR / "recalibration.md", encoding="utf-8").read())
