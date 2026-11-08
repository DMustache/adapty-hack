"""SIMULATED – pipeline check, not a result.

    python -m ml.usage.simulated_check [--data-dir PATH] [--scenario null|signal|both]

The Lumen dataset has NO usage data. This generates synthetic app activity to exercise the whole pipeline end to end:
Amplitude-format export -> loader -> customer_user_id matching -> point-in-time usage features -> baseline (deployed
23 features) vs usage model (ml/temporal_churn/train_usage.py) -> report.

Scenarios (seeded, reproducible):
  * null   : each subscriber has a steady random session rate, unrelated to churn. A correct, leak-free pipeline should
             show no meaningful gain.
  * signal : same, but sessions of subscribers whose final period ends in churn fade to 25% over the 14 days before
             that renewal. The signal is injected FROM THE KNOWN OUTCOME, so any gain is artificial by construction.
Every output is labelled "SIMULATED – pipeline check, not a result". Exports go to a temporary folder; the deployed
model and the service's model folder are never written; no Adapty calls.
"""
from __future__ import annotations

import argparse
import gzip
import json
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from ml.temporal_churn import snapshots as S
from ml.temporal_churn import train_usage as TU
from ml.usage.loader import load_exports, match, subscribers_from_offline

LABEL = TU.SIMULATED_LABEL
RUN_ID = "261329"
FADE_DAYS = 14
FADE_TO = 0.25
DECOY_SHARE = 0.3
UNTRACKED_SHARE = 0.2      # subscribers with no usage history at all (tests the optional/null path)


def synthetic_events(users: pd.DataFrame, tx: pd.DataFrame, cutoff: pd.Timestamp, scenario: str,
                     rng: np.random.Generator, run_id: str = RUN_ID) -> pd.DataFrame:
    """SIMULATED usage events: session_start (+ decoy photo_edited) per subscriber, source = "simulated".

    user_id = the customer_user_id the seeder used (lumen_<run>_<n>); subscriber_id = the offline user id.
    """
    p = S.periods(tx)
    last = p.sort_values("k").groupby("user_id").tail(1).set_index("user_id")
    end = last["expires_at"].clip(upper=cutoff)
    churned_due = last.loc[~last["renewed"] & (last["expires_at"] <= cutoff), "expires_at"]
    inst = users.set_index("user_id")["install_at"]
    uids, names, times = [], [], []
    for uid in last.index:
        if rng.random() < UNTRACKED_SHARE:
            continue
        start, stop = inst[uid], end[uid]
        days = int(np.ceil((stop - start) / pd.Timedelta(days=1)))
        if days <= 0:
            continue
        day_starts = start.normalize() + pd.to_timedelta(np.arange(days), unit="D")
        lam = np.full(days, rng.gamma(2.0, 0.75))                         # mean 1.5 sessions/day
        if scenario == "signal" and uid in churned_due.index:
            to_due = (churned_due[uid] - day_starts) / pd.Timedelta(days=1)
            fade = np.clip(1 - (FADE_DAYS - to_due) / FADE_DAYS, 0, 1)
            lam = lam * np.where(to_due <= FADE_DAYS, FADE_TO + (1 - FADE_TO) * fade, 1.0)
        counts = rng.poisson(lam)
        n = int(counts.sum())
        if not n:
            continue
        t = day_starts.repeat(counts) + pd.to_timedelta(rng.uniform(0, 86400, n), unit="s")
        t = t[(t >= start) & (t <= stop)]
        decoy = t[rng.random(len(t)) < DECOY_SHARE]
        cuid = f"lumen_{run_id}_{uid[1:]}"
        uids += [cuid] * (len(t) + len(decoy))
        names += ["session_start"] * len(t) + ["photo_edited"] * len(decoy)
        times += list(t) + list(decoy)
    ev = pd.DataFrame({"user_id": uids, "event_name": names, "occurred_at": pd.to_datetime(times, utc=True),
                       "source": "simulated", "source_event_id": None})
    return ev.sort_values(["user_id", "occurred_at"]).reset_index(drop=True)


def write_amplitude_export(events: pd.DataFrame, path: Path) -> None:
    """Write events as an Amplitude Export API file (JSON lines), marked as simulated in event_properties."""
    with gzip.open(path, "wt", encoding="utf-8") as f:
        for r in events.itertuples(index=False):
            f.write(json.dumps({"user_id": r.user_id, "event_type": r.event_name,
                                "event_time": r.occurred_at.strftime("%Y-%m-%d %H:%M:%S.%f"),
                                "event_properties": {"simulated": True}}) + "\n")


def run(scenario: str, data_dir=None, seed: int = 11, grid=None, out_dir: Path | None = None) -> dict:
    users, tx, cutoff = S.load(data_dir)
    rng = np.random.default_rng(seed + (0 if scenario == "null" else 1))
    ev = synthetic_events(users, tx, cutoff, scenario, rng)
    with tempfile.TemporaryDirectory() as d:          # round trip through the real Amplitude loader
        path = Path(d) / f"SIMULATED_amplitude_{scenario}.jsonl.gz"
        write_amplitude_export(ev, path)
        loaded, stats = load_exports([path])
    matched, report = match(loaded, subscribers_from_offline(S.find_data_dir(data_dir) / "users.csv.gz", RUN_ID))
    snaps = S.add_usage_features(S.build_snapshots(users, tx, cutoff), matched)
    res, _ = TU.evaluate(snaps, cutoff, grid=grid, simulated=True)
    res["scenario"] = scenario
    res["usage_match"] = {**stats, **report}
    TU.write_report(res, out_dir or TU.T.REPORT_DIR, stem=f"usage_pipeline_check_{scenario}")
    return res


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir")
    ap.add_argument("--scenario", choices=["null", "signal", "both"], default="both")
    args = ap.parse_args()
    for sc in (["null", "signal"] if args.scenario == "both" else [args.scenario]):
        r = run(sc, args.data_dir)
        g = r["brier_gain_usage_vs_baseline"]
        print(f"[{LABEL}] {sc}: Brier gain {g['estimate']:+.5f} CI {g['ci95']} passes={r['acceptance_rule']['passes']} "
              f"coverage test={r['info']['usage_coverage']['test']['share_with_usage']:.1%}")


if __name__ == "__main__":
    main()
