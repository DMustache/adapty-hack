"""SIMULATED – pipeline check, not a result.

    python -m ml.usage.simulated_check [--data-dir PATH]

The Lumen dataset has NO usage data, so this generates synthetic app-usage exports to exercise the whole usage
pipeline end to end: Amplitude-format export -> loader -> customer_user_id matching -> point-in-time features ->
CatBoost with vs without usage features -> evaluation by days before renewal (temporal holdout).

Two synthetic scenarios (seeded, reproducible):
  * null    : each subscriber has a steady random session rate, unrelated to churn. A correct pipeline should show
              no meaningful gain from usage features.
  * signal  : same, but sessions of subscribers whose final period ends in churn fade linearly to 25% over the 14 days
              before that renewal. The signal is injected FROM THE KNOWN OUTCOME, so any gain is artificial by
              construction; it only shows the pipeline can pick such a signal up.
Synthetic usage is generated for training and holdout subscribers (a model with usage features needs training data).
Exports are written to a temporary folder and discarded. The deployed model is not modified; no Adapty calls.
Every output is marked "SIMULATED – pipeline check, not a result".
"""
from __future__ import annotations

import argparse
import gzip
import json
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from ml.temporal_churn import horizon_eval as H
from ml.temporal_churn import snapshots as S
from ml.temporal_churn.train import ARTIFACT_DIR, SEED, fit, holdout, predict
from ml.usage.features import USAGE_FEATURES, usage_features
from ml.usage.loader import load_exports, match, subscribers_from_offline

LABEL = "SIMULATED – pipeline check, not a result"
REPORT_DIR = Path(__file__).resolve().parent / "reports"
RUN_ID = "261329"
FADE_DAYS = 14
FADE_TO = 0.25
DECOY_SHARE = 0.3


def write_synthetic_export(path: Path, users: pd.DataFrame, tx: pd.DataFrame, cutoff: pd.Timestamp,
                           scenario: str, rng) -> dict:
    """Amplitude-style JSON lines: session_start events (+ decoy photo_edited events) per subscriber."""
    p = S.periods(tx)
    last = p.sort_values("k").groupby("user_id").tail(1).set_index("user_id")
    end = last["expires_at"].clip(upper=cutoff)
    churned_due = last.loc[~last["renewed"] & (last["expires_at"] <= cutoff), "expires_at"]
    inst = users.set_index("user_id")["install_at"]
    n_sess = n_decoy = 0
    with gzip.open(path, "wt", encoding="utf-8") as f:
        for uid in last.index:
            start, stop = inst[uid], end[uid]
            days = int(np.ceil((stop - start) / pd.Timedelta(days=1)))
            if days <= 0:
                continue
            rate = rng.gamma(2.0, 0.75)                                  # mean 1.5 sessions/day
            day0 = start.normalize()
            day_starts = day0 + pd.to_timedelta(np.arange(days), unit="D")
            lam = np.full(days, rate)
            if scenario == "signal" and uid in churned_due.index:
                due = churned_due[uid]
                to_due = (due - day_starts) / pd.Timedelta(days=1)
                fade = np.clip(1 - (FADE_DAYS - to_due) / FADE_DAYS, 0, 1)
                lam = lam * np.where(to_due <= FADE_DAYS, FADE_TO + (1 - FADE_TO) * fade, 1.0)
            counts = rng.poisson(lam)
            cuid = f"lumen_{RUN_ID}_{uid[1:]}"
            for d, c in zip(day_starts, counts):
                for _ in range(c):
                    t = d + pd.Timedelta(seconds=float(rng.uniform(0, 86400)))
                    if start <= t <= stop:
                        f.write(json.dumps({"user_id": cuid, "event_type": "session_start",
                                            "event_time": t.strftime("%Y-%m-%d %H:%M:%S.%f")}) + "\n")
                        n_sess += 1
                        if rng.random() < DECOY_SHARE:
                            f.write(json.dumps({"user_id": cuid, "event_type": "photo_edited",
                                                "event_time": t.strftime("%Y-%m-%d %H:%M:%S.%f")}) + "\n")
                            n_decoy += 1
        # a few events from users who are not subscribers, to exercise matching
        for i in range(25):
            f.write(json.dumps({"user_id": f"not_a_subscriber_{i}", "event_type": "session_start",
                                "event_time": "2026-10-01 12:00:00.000000"}) + "\n")
    return {"session_events": n_sess, "decoy_events": n_decoy, "non_subscriber_events": 25,
            "subscribers_with_usage": int(len(last))}


def main(data_dir=None) -> dict:
    rng = np.random.default_rng(SEED)
    meta = json.loads((ARTIFACT_DIR / "metadata.json").read_text(encoding="utf-8"))
    params, base = meta["params"], meta["features"]
    users, tx, cutoff = S.load(data_dir)
    snaps = S.build_snapshots(users, tx, cutoff)
    train, test, test_start = holdout(snaps, cutoff)
    subs = subscribers_from_offline(S.find_data_dir(data_dir) / "users.csv.gz", RUN_ID)
    p_without = predict(fit(train, base, params), test, base)
    on = ~test["auto_renew_off"].astype(bool).to_numpy()
    out = {"label": LABEL, "simulated": True, "deployed_model_modified": False, "scenarios": {}}
    for scenario in ("null", "signal"):
        with tempfile.TemporaryDirectory() as tmp:
            export = Path(tmp) / f"amplitude_{scenario}.jsonl.gz"
            gen = write_synthetic_export(export, users, tx, cutoff, scenario, rng)
            events, load_stats = load_exports([export])
        matched, report = match(events, subs)
        tr = train.join(usage_features(train, matched))
        te = test.join(usage_features(test, matched))
        feats = base + USAGE_FEATURES
        p_with = predict(fit(tr, feats, params), te, feats)
        out["scenarios"][scenario] = {
            "label": LABEL, "generated": gen, "loader": load_stats, "matching": report,
            "auto_renew_on": {"without_usage": H.by_bucket(test[on], p_without[on], rng),
                              "with_usage": H.by_bucket(te[on], p_with[on], rng)},
            "all_snapshots": {"without_usage": H.by_bucket(test, p_without, rng),
                              "with_usage": H.by_bucket(te, p_with, rng)}}
    REPORT_DIR.mkdir(exist_ok=True)
    (REPORT_DIR / "SIMULATED_usage_pipeline_check.json").write_text(json.dumps(out, indent=1, default=str),
                                                                     encoding="utf-8")
    (REPORT_DIR / "SIMULATED_usage_pipeline_check.md").write_text(render(out, test_start), encoding="utf-8")
    return out


def render(o: dict, test_start) -> str:
    L = [f"# {LABEL.upper()}", "",
         f"> **{LABEL}.** The Lumen dataset contains no usage data. All usage events below are synthetic, generated "
         "only to check that the usage pipeline works end to end. None of these numbers describes real users or the "
         "deployed model, and none may be quoted as a model improvement. The deployed model was not changed.", "",
         f"Holdout from {test_start:%d %b %Y}. Without usage = the deployed feature set; with usage = + "
         f"{', '.join(USAGE_FEATURES)}. 95% CIs: subscriber-clustered bootstrap.", ""]
    for scenario, s in o["scenarios"].items():
        title = ("Scenario `null`: usage unrelated to churn (expected: no gain)" if scenario == "null" else
                 "Scenario `signal`: churners' sessions fade before renewal, injected from the known outcome "
                 "(expected: artificial gain)")
        m, g, ld = s["matching"], s["generated"], s["loader"]
        L += [f"## {LABEL}: {title}", "",
              f"Generated {g['session_events']:,} session + {g['decoy_events']:,} decoy + "
              f"{g['non_subscriber_events']} non-subscriber events. Loader kept {ld['rows_kept']:,} of "
              f"{ld['rows_read']:,} rows; matched {m['matched_users']:,} of {m['event_users']:,} event users "
              f"({m['unmatched_users']} unmatched, e.g. {', '.join(m['unmatched_examples'][:2])}).", ""]
        for subset, name in (("auto_renew_on", "auto-renew ON snapshots"), ("all_snapshots", "all snapshots")):
            L += [f"**{LABEL}: {name}**", "",
                  "| Days before renewal | Variant | Snapshots | Churned | Churn rate | ROC-AUC (95% CI) | "
                  "PR-AUC (95% CI) | Lost revenue in top 10% (95% CI) |", "|---|---|---|---|---|---|---|---|"]
            for bucket in s[subset]["without_usage"]:
                for variant in ("without_usage", "with_usage"):
                    L.append(f"| {bucket} | {variant.replace('_', ' ')} (SIMULATED) | "
                             + H.fmt(s[subset][variant][bucket]))
            L.append("")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir")
    main(ap.parse_args().data_dir)
    print((REPORT_DIR / "SIMULATED_usage_pipeline_check.md").read_text(encoding="utf-8"))
