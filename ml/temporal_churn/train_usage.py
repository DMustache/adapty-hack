"""Train and evaluate the churn model WITH app-usage features against the unchanged 23-feature baseline.

    python -m ml.temporal_churn.train_usage --usage EXPORT [EXPORT ...] [--format amplitude|firebase|csv]
           [--users-csv PATH --run-id 261329 | --profiles PATH] [--data-dir PATH]
           [--export [--artifact-dir DIR]] [--simulated]
    python -m ml.temporal_churn.train_usage --database-url URL ...      # read the usage_events table instead

Both models are CatBoost on the same point-in-time snapshots, labels, temporal holdout, chronological CV grid and
seed as ml/temporal_churn/train.py:
  * temporal        : the deployed 23 features (baseline, unchanged; this script never touches its artifact)
  * temporal_usage  : the same 23 + USAGE_FEATURES (null when a subscriber has no usage history before as_of_at)

Acceptance rule (same as every earlier feature experiment): the usage model must have a lower Brier score in EVERY
chronological CV fold AND a subscriber-clustered bootstrap 95% CI of the holdout Brier gain above zero. The verdict
is recorded in the report and in the artifact metadata; it never deploys anything.

--export writes services/inference/models/temporal_usage_catboost/ (model_id lumen-temporal-usage-catboost), which the
inference service loads as an ADDITIONAL model next to the deployed one. Models trained on simulated usage
(--simulated, or events with source "simulated") can only be exported to an explicit --artifact-dir, never to the
service's model folder, and all their outputs are labelled SIMULATED.
"""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss, log_loss

from ml.temporal_churn import snapshots as S
from ml.temporal_churn import train as T
from ml.usage.features import USAGE_FEATURES

USAGE_ARTIFACT_DIR = T.ROOT / "services" / "inference" / "models" / "temporal_usage_catboost"
USAGE_MODEL_ID = "lumen-temporal-usage-catboost"
USAGE_MODEL_VERSION = "0.1.0"
BASELINE, CANDIDATE = "temporal", "temporal_usage"
SIMULATED_LABEL = "SIMULATED – pipeline check, not a result"


def coverage(df: pd.DataFrame) -> dict:
    tracked = df[USAGE_FEATURES].notna().any(axis=1)
    return {"snapshots": len(df), "with_usage": int(tracked.sum()),
            "share_with_usage": float(tracked.mean()) if len(df) else 0.0,
            "subscribers_with_usage": int(df.loc[tracked, "user_id"].nunique())}


def evaluate(snaps: pd.DataFrame, cutoff: pd.Timestamp, grid: list[dict] | None = None,
             simulated: bool = False, seed: int = T.SEED) -> tuple[dict, dict]:
    """Train baseline and usage model on `snaps` (must already carry USAGE_FEATURES). Returns (report, models)."""
    grid = grid or T.GRID
    rng = np.random.default_rng(seed)
    train, test, test_start = T.holdout(snaps, cutoff)
    if train.empty or test.empty or train["churn"].nunique() < 2 or test["churn"].nunique() < 2:
        raise ValueError("not enough labelled snapshots with both outcomes for a temporal holdout")
    folds = list(T.chrono_folds(train))
    y, price, groups = test["churn"].to_numpy(), test["renewal_price_usd"].to_numpy(float), test["user_id"].to_numpy()
    results, preds, models = {}, {}, {}
    for name in (BASELINE, CANDIDATE):
        features = S.FEATURE_SETS[name]
        cv = []
        for params in grid:
            ll = [log_loss(train["churn"].iloc[val], T.predict(T.fit(train.iloc[trn], features, params),
                                                                train.iloc[val], features), labels=[0, 1])
                  for trn, val in folds if len(trn) and len(val)]
            cv.append((float(np.mean(ll)) if ll else float("inf"), params))
        best = min(cv, key=lambda c: c[0])[1]
        # per-fold Brier with the chosen parameters (the "better in every fold" half of the acceptance rule)
        fold_brier = []
        for trn, val in folds:
            if len(trn) and len(val) and train["churn"].iloc[trn].nunique() == 2:
                m = T.fit(train.iloc[trn], features, best)
                fold_brier.append(float(brier_score_loss(train["churn"].iloc[val],
                                                         T.predict(m, train.iloc[val], features))))
        models[name] = T.fit(train, features, best)
        preds[name] = T.predict(models[name], test, features)
        results[name] = {"features": len(features), "params": best, "cv_log_loss": [c[0] for c in cv],
                         "fold_brier": fold_brier, "test": T.metrics(y, preds[name], price),
                         "by_horizon": T.by_horizon(test, preds[name])}
    gain = T.cluster_boot(y, preds[BASELINE], preds[CANDIDATE], groups, rng)
    fb, fc = results[BASELINE]["fold_brier"], results[CANDIDATE]["fold_brier"]
    every_fold = bool(fb) and len(fb) == len(fc) and all(c < b for b, c in zip(fb, fc))
    passes = every_fold and gain[1] > 0
    tracked = test[USAGE_FEATURES].notna().any(axis=1).to_numpy()
    subset = {}
    for label, mask in (("with_usage", tracked), ("without_usage", ~tracked)):
        if mask.sum() and 0 < y[mask].mean() < 1:
            subset[label] = {n: {"n": int(mask.sum()), "brier": float(brier_score_loss(y[mask], preds[n][mask]))}
                             for n in (BASELINE, CANDIDATE)}
    report = {
        "label": SIMULATED_LABEL if simulated else "real usage data",
        "simulated": simulated,
        "info": {"observation_cutoff": cutoff.isoformat(), "test_start": test_start.isoformat(),
                 "train_rows": len(train), "test_rows": len(test),
                 "usage_coverage": {"train": coverage(train), "test": coverage(test)}},
        "models": results,
        "brier_gain_usage_vs_baseline": {"estimate": gain[0], "ci95": [gain[1], gain[2]]},
        "subsets": subset,
        "acceptance_rule": {"better_in_every_fold": every_fold, "ci_above_zero": gain[1] > 0, "passes": passes},
        "verdict": verdict(passes, simulated),
    }
    return report, models


def verdict(passes: bool, simulated: bool) -> str:
    if simulated:
        return (f"{SIMULATED_LABEL}. The usage features were computed from synthetic activity, so this shows only "
                "that the pipeline runs end to end; it says nothing about real accuracy. Keep the deployed model.")
    if passes:
        return ("Usage model passed the acceptance rule on this data. Review the report, then decide on deployment "
                "(the deployed 23-feature model is unchanged).")
    return "Usage model did not pass the acceptance rule. Keep the deployed 23-feature model."


def export_usage_model(model, report: dict, artifact_dir: Path | None = None, usage_source: str = "") -> Path:
    simulated = report["simulated"]
    if simulated and artifact_dir is None:
        raise ValueError("a model trained on simulated usage can only be exported to an explicit --artifact-dir")
    base = json.loads((T.ARTIFACT_DIR / "metadata.json").read_text(encoding="utf-8"))
    r = report["models"][CANDIDATE]
    return T.export(model, S.FEATURE_SETS[CANDIDATE], {
        "target": "failure to renew at the next eligible renewal event (any reason)",
        "unit": "active weekly/monthly paid subscriber at as_of_at (point-in-time snapshot)",
        "data": f"Lumen offline subscriptions (SYNTHETIC) + usage events ({usage_source or 'unspecified source'})",
        "label": report["label"], "simulated": simulated,
        "baseline_model": {"model_id": base["model_id"], "model_version": base["model_version"],
                           "sha256": base["sha256"], "features": base["features"]},
        "usage_features": USAGE_FEATURES, "optional_features": USAGE_FEATURES,
        "missing_usage": "omit or send null: the model was trained with nulls for subscribers without usage history",
        "split": report["info"], "params": r["params"],
        "metrics": {k: v for k, v in r["test"].items() if k != "calibration"},
        "acceptance_rule": report["acceptance_rule"], "verdict": report["verdict"],
        "trained_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
    }, artifact_dir=artifact_dir or USAGE_ARTIFACT_DIR, model_id=USAGE_MODEL_ID, model_version=USAGE_MODEL_VERSION,
        optional=USAGE_FEATURES)


def render(o: dict) -> str:
    i, cov = o["info"], o["info"]["usage_coverage"]
    L = [f"# Churn model with app-usage features vs the deployed baseline ({o['label']})", ""]
    if o["simulated"]:
        L += [f"> **{SIMULATED_LABEL}.** Usage events are synthetic; no accuracy claim can be made from this.", ""]
    L += [(f"Observation cutoff {i['observation_cutoff'][:16]} UTC; holdout from {i['test_start'][:10]}. "
          f"Train {i['train_rows']:,} / test {i['test_rows']:,} snapshots."), "",
          (f"Usage coverage: train {cov['train']['share_with_usage']:.1%} of snapshots "
          f"({cov['train']['subscribers_with_usage']:,} subscribers), test {cov['test']['share_with_usage']:.1%} "
          f"({cov['test']['subscribers_with_usage']:,})."), "",
          "| Model | Features | Brier (base rate) | PR-AUC | ROC-AUC | ECE | Fold Briers |", "|---|---|---|---|---|---|---|"]
    for n, r in o["models"].items():
        t = r["test"]
        L.append(f"| {n}{' (baseline, deployed)' if n == BASELINE else ''} | {r['features']} | {t['brier']:.4f} "
                 f"({t['brier_base_rate']:.4f}) | {t['pr_auc']:.3f} | {t['roc_auc']:.3f} | {t['ece']:.4f} | "
                 + ", ".join(f"{b:.4f}" for b in r["fold_brier"]) + " |")
    g, a = o["brier_gain_usage_vs_baseline"], o["acceptance_rule"]
    L += ["", (f"Brier gain, usage vs baseline (positive = usage better): {g['estimate']:+.5f} "
              f"(95% CI {g['ci95'][0]:+.5f} to {g['ci95'][1]:+.5f})."),
          (f"Better in every fold: {a['better_in_every_fold']}; CI above zero: {a['ci_above_zero']}; "
          f"**passes: {a['passes']}**."), ""]
    for label, s in o["subsets"].items():
        L.append(f"- Test snapshots {label.replace('_', ' ')} (n={s[BASELINE]['n']:,}): Brier baseline "
                 f"{s[BASELINE]['brier']:.4f}, usage {s[CANDIDATE]['brier']:.4f}")
    L += ["", f"**Verdict:** {o['verdict']}", ""]
    for n, r in o["models"].items():
        L += [f"## {n}: by days until renewal", "", "| Days | n | Churn | Brier | PR-AUC |", "|---|---|---|---|---|"]
        L += [f"| {h['days_until_renewal']} | {h['n']:,} | {h['churn_rate']:.1%} | {h['brier']:.4f} | "
              f"{h['pr_auc']:.3f} |" for h in r["by_horizon"]] + [""]
    return "\n".join(L)


def write_report(report: dict, out_dir: Path, stem: str = "usage_evaluation") -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    if report["simulated"]:
        stem = f"SIMULATED_{stem}"
    (out_dir / f"{stem}.json").write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    (out_dir / f"{stem}.md").write_text(render(report), encoding="utf-8")
    return out_dir / f"{stem}.md"


def load_usage(args, users_csv: Path) -> tuple[pd.DataFrame, dict, str]:
    """Usage events matched to snapshot user ids, the match report and a short source description."""
    from ml.usage import loader as L
    if args.database_url:
        events, stats = L.read_events(args.database_url), {}
        source = "usage_events table"
    else:
        events, stats = L.load_exports(args.usage, args.format)
        source = ", ".join(sorted(events["source"].unique())) or "empty export"
    subs = L.subscribers_from_profiles(args.profiles) if args.profiles else \
        L.subscribers_from_offline(args.users_csv or users_csv, args.run_id)
    matched, report = L.match(events, subs)
    return matched, {**stats, **report}, source


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--usage", nargs="+", metavar="EXPORT", help="Amplitude / Firebase / CSV export file(s)")
    src.add_argument("--database-url", help="read usage events from the usage_events table")
    ap.add_argument("--format", choices=["amplitude", "firebase", "csv"])
    ap.add_argument("--data-dir")
    ap.add_argument("--users-csv")
    ap.add_argument("--run-id", default="261329")
    ap.add_argument("--profiles")
    ap.add_argument("--simulated", action="store_true", help="the usage events are synthetic (labels every output)")
    ap.add_argument("--export", action="store_true", help="write the usage-model artifact")
    ap.add_argument("--artifact-dir", type=Path)
    ap.add_argument("--report-dir", type=Path, default=T.REPORT_DIR)
    args = ap.parse_args()
    users, tx, cutoff = S.load(args.data_dir)
    events, match_report, source = load_usage(args, S.find_data_dir(args.data_dir) / "users.csv.gz")
    simulated = args.simulated or bool((events.get("source") == "simulated").any())
    print(json.dumps(match_report, indent=1, default=str))
    snaps = S.add_usage_features(S.build_snapshots(users, tx, cutoff), events)
    report, models = evaluate(snaps, cutoff, simulated=simulated)
    report["usage_match"] = match_report
    print(f"report: {write_report(report, args.report_dir)}")
    for n, r in report["models"].items():
        t = r["test"]
        print(f"{n:16s} Brier {t['brier']:.4f} PR-AUC {t['pr_auc']:.3f} AUC {t['roc_auc']:.3f} folds {r['fold_brier']}")
    print(report["acceptance_rule"], report["verdict"], sep="\n")
    if args.export:
        print(f"exported {export_usage_model(models[CANDIDATE], report, args.artifact_dir, source)}")


if __name__ == "__main__":
    main()
