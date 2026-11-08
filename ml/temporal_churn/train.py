"""Train and evaluate the temporal churn model; export the deployed CatBoost artifact.

    python -m ml.temporal_churn.train [--data-dir PATH]

Models (all CatBoost, same snapshots and labels, fixed seed):
  * static             : sign-up attributes only (baseline)
  * temporal_behaviour : + tenure, renewal count, days until renewal, days since payment, renewal/billing history
  * temporal           : + auto-renew status as of the snapshot (DEPLOYED)

Temporal holdout: test = labelled snapshots with as_of_at in the last TEST_DAYS before the last resolvable renewal;
train = labelled snapshots whose renewal was resolved BEFORE the test window starts (no training outcome overlaps
the test period). Hyperparameters: small grid, chosen by chronological forward-chaining CV inside the training
period (purged the same way). No random CV.

Outputs: services/inference/models/temporal_catboost/{model.cbm, model.cbm.sha256, metadata.json}
         ml/temporal_churn/reports/evaluation.{md,json}
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from catboost import CatBoostClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, log_loss, roc_auc_score

from ml.temporal_churn import snapshots as S

ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_DIR = ROOT / "services" / "inference" / "models" / "temporal_catboost"
REPORT_DIR = Path(__file__).resolve().parent / "reports"
MODEL_ID = "lumen-temporal-catboost"
MODEL_VERSION = "1.0.0"
SEED = 7
TEST_DAYS = 28
N_FOLDS = 3
# Regularized grid (weak signal: an unregularized model overfits and loses to the base rate). Chosen by
# chronological CV log loss only; the holdout is never used for tuning.
GRID = [{"depth": d, "iterations": it, "learning_rate": 0.03, "l2_leaf_reg": 10}
        for d in (3, 4, 6) for it in (100, 300)]
N_BOOT = 500
EPS = 1e-6


# ---------------------------------------------------------------- data split
def holdout(s: pd.DataFrame, cutoff: pd.Timestamp):
    lab = s[s["churn"].notna()].copy()
    last_resolvable = cutoff - pd.Timedelta(days=S.OUTCOME_MARGIN_DAYS)
    test_start = last_resolvable - pd.Timedelta(days=TEST_DAYS)
    test = lab[lab["as_of_at"] >= test_start]
    train = lab[lab["renewal_due_at"] < test_start]          # outcome resolved before the test window
    return train.reset_index(drop=True), test.reset_index(drop=True), test_start


def chrono_folds(train: pd.DataFrame):
    t0, t1 = train["as_of_at"].min(), train["as_of_at"].max()
    edges = pd.date_range(t0 + (t1 - t0) * 0.4, t1 + pd.Timedelta(seconds=1), periods=N_FOLDS + 1)
    for a, b in zip(edges[:-1], edges[1:]):
        val = np.where((train["as_of_at"] >= a) & (train["as_of_at"] < b))[0]
        trn = np.where(train["renewal_due_at"] < a)[0]
        yield trn, val


# ---------------------------------------------------------------- model
def matrix(df: pd.DataFrame, features: list[str]) -> pd.DataFrame:
    x = df[features].copy()
    for f in features:
        if f in S.CATEGORICAL:
            x[f] = x[f].astype(str)
        elif f in S.BOOLEAN:
            x[f] = x[f].astype(float)
        else:
            x[f] = pd.to_numeric(x[f], errors="coerce").astype(float)
    return x


def fit(df: pd.DataFrame, features: list[str], params: dict) -> CatBoostClassifier:
    m = CatBoostClassifier(iterations=params["iterations"], depth=params["depth"],
                           learning_rate=params.get("learning_rate", 0.03), l2_leaf_reg=params.get("l2_leaf_reg", 10),
                           random_seed=SEED, verbose=0, thread_count=4, allow_writing_files=False,
                           cat_features=[f for f in features if f in S.CATEGORICAL])
    return m.fit(matrix(df, features), df["churn"].astype(int).to_numpy())


def predict(m: CatBoostClassifier, df: pd.DataFrame, features: list[str]) -> np.ndarray:
    return np.clip(m.predict_proba(matrix(df, features))[:, 1], EPS, 1 - EPS)


# ---------------------------------------------------------------- metrics
def ece(y, p, bins=10):
    order = np.argsort(p)
    return float(sum(abs(y[c].mean() - p[c].mean()) * len(c) / len(y) for c in np.array_split(order, bins)))


def calibration(y, p, bins=10):
    order = np.argsort(p)
    return [{"bin": i + 1, "n": int(len(c)), "mean_predicted": float(p[c].mean()), "observed": float(y[c].mean())}
            for i, c in enumerate(np.array_split(order, bins))]


def calib_slope_intercept(y, p):
    m = LogisticRegression(C=1e6, max_iter=1000).fit(np.log(p / (1 - p)).reshape(-1, 1), y)
    return float(m.coef_[0][0]), float(m.intercept_[0])


def revenue_capture(y, p, price, frac):
    lost = y * price
    k = max(1, int(round(frac * len(y))))
    top = np.argsort(-(p * price), kind="stable")[:k]
    return float(lost[top].sum() / lost.sum()) if lost.sum() else float("nan")


def metrics(y, p, price) -> dict:
    slope, intercept = calib_slope_intercept(y, p)
    return {"n": int(len(y)), "churn_rate": float(y.mean()),
            "brier": float(brier_score_loss(y, p)), "brier_base_rate": float(brier_score_loss(y, np.full(len(y), y.mean()))),
            "log_loss": float(log_loss(y, p)), "pr_auc": float(average_precision_score(y, p)),
            "roc_auc": float(roc_auc_score(y, p)), "ece": ece(y, p), "calib_slope": slope,
            "calib_intercept": intercept, "rev_capture_10": revenue_capture(y, p, price, 0.10),
            "rev_capture_20": revenue_capture(y, p, price, 0.20), "calibration": calibration(y, p)}


def cluster_boot(y, pa, pb, groups, rng, n=N_BOOT):
    """Brier(a) - Brier(b) with a subscriber-clustered bootstrap 95% CI (positive = b better)."""
    ug, inv = np.unique(groups, return_inverse=True)
    sa, sb, cnt = np.bincount(inv, (pa - y) ** 2), np.bincount(inv, (pb - y) ** 2), np.bincount(inv)
    d = (sa.sum() - sb.sum()) / cnt.sum()
    boots = []
    for _ in range(n):
        i = rng.integers(0, len(ug), len(ug))
        boots.append((sa[i].sum() - sb[i].sum()) / cnt[i].sum())
    return float(d), float(np.quantile(boots, 0.025)), float(np.quantile(boots, 0.975))


def by_horizon(test: pd.DataFrame, p: np.ndarray) -> list[dict]:
    y = test["churn"].to_numpy()
    bins = pd.cut(test["days_until_renewal"], [0, 1, 2, 3, 5, 8, 31], include_lowest=True)
    out = []
    for b in bins.cat.categories:
        m = (bins == b).to_numpy()
        if m.sum() and 0 < y[m].mean() < 1:
            out.append({"days_until_renewal": str(b), "n": int(m.sum()), "churn_rate": float(y[m].mean()),
                        "brier": float(brier_score_loss(y[m], p[m])), "pr_auc": float(average_precision_score(y[m], p[m]))})
    return out


def trajectory_summary(test: pd.DataFrame, p: np.ndarray) -> list[dict]:
    """Mean predicted risk by days until renewal, separately for periods that ended in churn vs renewal."""
    t = test.assign(p=p, d=np.ceil(test["days_until_renewal"]).clip(upper=8))
    g = t.groupby(["d", "churn"])["p"].mean().unstack()
    return [{"days_until_renewal": int(d), "mean_p_renewed": float(r.get(0.0, np.nan)),
             "mean_p_churned": float(r.get(1.0, np.nan))} for d, r in g.sort_index(ascending=False).iterrows()]


# ---------------------------------------------------------------- export
def export(model: CatBoostClassifier, features: list[str], meta: dict, artifact_dir: Path | None = None,
           model_id: str = MODEL_ID, model_version: str = MODEL_VERSION, optional: list[str] | tuple = ()) -> Path:
    """Write model.cbm, its SHA-256 and metadata.json. Defaults = the deployed temporal model. `optional` features may
    be omitted or null in a request (e.g. usage features of a subscriber without usage history)."""
    artifact_dir = Path(artifact_dir or ARTIFACT_DIR)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    path = artifact_dir / "model.cbm"
    model.save_model(str(path), format="cbm")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    (artifact_dir / "model.cbm.sha256").write_text(f"{digest}  model.cbm\n", encoding="utf-8")
    schema = {"$schema": "https://json-schema.org/draft/2020-12/schema", "title": f"{model_id} features",
              "type": "object", "additionalProperties": False,
              "required": [f for f in features if f not in optional], "properties": {}}
    for f in features:
        if f in S.CATEGORICAL:
            schema["properties"][f] = {"type": ["string", "null"]}
        elif f in S.BOOLEAN:
            schema["properties"][f] = {"type": "boolean"}
        else:
            schema["properties"][f] = {"type": ["number", "null"]}
    metadata = {"model_id": model_id, "model_version": model_version, "format": "catboost-cbm",
                "sha256": digest, "features": features,
                "categorical_features": [f for f in features if f in S.CATEGORICAL],
                "boolean_features": [f for f in features if f in S.BOOLEAN], "input_schema": schema, **meta}
    (artifact_dir / "metadata.json").write_text(json.dumps(metadata, indent=1, default=str), encoding="utf-8")
    return path


# ---------------------------------------------------------------- main
def main(data_dir=None) -> dict:
    rng = np.random.default_rng(SEED)
    users, tx, cutoff = S.load(data_dir)
    snaps = S.build_snapshots(users, tx, cutoff)
    train, test, test_start = holdout(snaps, cutoff)
    y, price, groups = test["churn"].to_numpy(), test["renewal_price_usd"].to_numpy(float), test["user_id"].to_numpy()
    results, preds, models = {}, {}, {}
    for name, features in ((n, S.FEATURE_SETS[n]) for n in S.EVALUATED_MODELS):
        cv = []
        for params in GRID:
            ll = []
            for trn, val in chrono_folds(train):
                m = fit(train.iloc[trn], features, params)
                ll.append(log_loss(train["churn"].iloc[val], predict(m, train.iloc[val], features), labels=[0, 1]))
            cv.append((float(np.mean(ll)), params))
        best = min(cv, key=lambda c: c[0])[1]
        models[name] = fit(train, features, best)
        preds[name] = predict(models[name], test, features)
        results[name] = {"params": best, "cv_log_loss": [c[0] for c in cv], "test": metrics(y, preds[name], price),
                         "by_horizon": by_horizon(test, preds[name]),
                         "trajectory": trajectory_summary(test, preds[name])}
    comparisons = {f"{b}_vs_static": cluster_boot(y, preds["static"], preds[b], groups, rng)
                   for b in ("temporal_behaviour", "temporal")}
    comparisons["temporal_vs_temporal_behaviour"] = cluster_boot(y, preds["temporal_behaviour"], preds["temporal"],
                                                                 groups, rng)
    info = {"observation_cutoff": cutoff.isoformat(), "test_start": test_start.isoformat(),
            "train_rows": int(len(train)), "train_subscribers": int(train.user_id.nunique()),
            "train_as_of": [train.as_of_at.min().isoformat(), train.as_of_at.max().isoformat()],
            "test_rows": int(len(test)), "test_subscribers": int(test.user_id.nunique()),
            "test_as_of": [test.as_of_at.min().isoformat(), test.as_of_at.max().isoformat()],
            "censored_snapshots": int(snaps.churn.isna().sum()), "total_snapshots": int(len(snaps))}
    deployed = results["temporal"]["test"]
    export(models["temporal"], S.FEATURE_SETS["temporal"], {
        "target": "failure to renew at the next eligible renewal event (any reason)",
        "unit": "active weekly/monthly paid subscriber at as_of_at (point-in-time snapshot)",
        "data": "Adapty hackathon Lumen offline dataset (SYNTHETIC)", "split": info,
        "params": results["temporal"]["params"],
        "metrics": {k: v for k, v in deployed.items() if k != "calibration"},
        "trained_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat()})
    out = {"info": info, "models": results, "comparisons": comparisons}
    REPORT_DIR.mkdir(exist_ok=True)
    (REPORT_DIR / "evaluation.json").write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    (REPORT_DIR / "evaluation.md").write_text(render(out), encoding="utf-8")
    return out


def render(o: dict) -> str:
    i = o["info"]
    L = ["# Temporal churn model: evaluation", "",
         f"Synthetic Lumen data. Observation cutoff {i['observation_cutoff'][:16]} UTC. Point-in-time snapshots of "
         f"active weekly/monthly subscribers; target = no renewal at the next eligible renewal event.", "",
         f"- Train: {i['train_rows']:,} snapshots, {i['train_subscribers']:,} subscribers, as-of "
         f"{i['train_as_of'][0][:10]} – {i['train_as_of'][1][:10]}; every training renewal resolved before "
         f"{i['test_start'][:10]}.",
         f"- Untouched temporal holdout: {i['test_rows']:,} snapshots, {i['test_subscribers']:,} subscribers, as-of "
         f"{i['test_as_of'][0][:10]} – {i['test_as_of'][1][:10]}.",
         f"- Censored (renewal not yet resolved, excluded from train and test): {i['censored_snapshots']:,} of "
         f"{i['total_snapshots']:,} snapshots.", "",
         "| Model | Brier (base rate) | Log loss | PR-AUC | ROC-AUC | ECE | Calib. slope / int. | Lost revenue in top 10% / 20% |",
         "|---|---|---|---|---|---|---|---|"]
    for n, r in o["models"].items():
        t = r["test"]
        tag = " (**deployed**)" if n == "temporal" else (" (baseline)" if n == "static" else "")
        L.append(f"| {n}{tag} | {t['brier']:.4f} ({t['brier_base_rate']:.4f}) | {t['log_loss']:.4f} | "
                 f"{t['pr_auc']:.3f} | {t['roc_auc']:.3f} | {t['ece']:.4f} | {t['calib_slope']:.2f} / "
                 f"{t['calib_intercept']:+.2f} | {t['rev_capture_10']:.1%} / {t['rev_capture_20']:.1%} |")
    L += ["", "Brier improvement (subscriber-clustered bootstrap 95% CI; positive = second model better):", ""]
    for k, (d, lo, hi) in o["comparisons"].items():
        L.append(f"- {k.replace('_vs_', ' vs ')}: {d:+.5f} ({lo:+.5f} to {hi:+.5f})")
    for n, r in o["models"].items():
        L += ["", f"## {n}", "", f"CatBoost {r['params']} (chronological CV log loss per grid point: "
              + ", ".join(f"{v:.4f}" for v in r["cv_log_loss"]) + ")", "",
              "| Days until renewal | n | Churn | Brier | PR-AUC |", "|---|---|---|---|---|"]
        L += [f"| {h['days_until_renewal']} | {h['n']:,} | {h['churn_rate']:.1%} | {h['brier']:.4f} | {h['pr_auc']:.3f} |"
              for h in r["by_horizon"]]
        L += ["", "Mean predicted risk as renewal approaches:", "", "| Days until renewal | Renewed | Churned |",
              "|---|---|---|"]
        L += [f"| {t['days_until_renewal']}{'+' if t['days_until_renewal'] == 8 else ''} | {t['mean_p_renewed']:.3f} | "
              f"{t['mean_p_churned']:.3f} |" for t in r["trajectory"]]
        L += ["", "| Calibration bin | n | Mean predicted | Observed |", "|---|---|---|---|"]
        L += [f"| {c['bin']} | {c['n']:,} | {c['mean_predicted']:.3f} | {c['observed']:.3f} |"
              for c in r["test"]["calibration"]]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir")
    res = main(ap.parse_args().data_dir)
    for n, r in res["models"].items():
        t = r["test"]
        print(f"{n:20s} Brier {t['brier']:.4f} (base {t['brier_base_rate']:.4f}) PR-AUC {t['pr_auc']:.3f} "
              f"AUC {t['roc_auc']:.3f} ECE {t['ece']:.4f} slope {t['calib_slope']:.2f} "
              f"rev@10 {t['rev_capture_10']:.1%} params {r['params']}")
    for k, v in res["comparisons"].items():
        print(k, [round(x, 5) for x in v])
    print(res["info"])
