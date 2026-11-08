"""Write tests/fixtures/temporal_churn_fixture.json: a few real snapshots and the deployed model's outputs.

    python -m ml.temporal_churn.make_fixture [--data-dir PATH]

Re-run only when the model artifact is intentionally replaced; the adapter test then pins its behaviour.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from ml.temporal_churn import snapshots as S
from services.inference.app.adapters.temporal_catboost import TemporalCatBoostAdapter

OUT = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "temporal_churn_fixture.json"


def main(data_dir=None) -> None:
    users, tx, cutoff = S.load(data_dir)
    s = S.build_snapshots(users, tx, cutoff)
    # deterministic, varied picks: early/late in a period, auto-renew on/off, weekly/monthly, censored
    picks = [s[(s.plan == "weekly") & (s.days_until_renewal >= 6)].iloc[0],
             s[(s.plan == "weekly") & (s.days_until_renewal <= 1)].iloc[0],
             s[s.auto_renew_off].iloc[0],
             s[s.plan == "monthly"].iloc[0],
             s[s.churn.isna()].iloc[-1]]
    adapter = TemporalCatBoostAdapter()
    adapter.load()
    cases = []
    for r in picks:
        feats = S.feature_record(r, "temporal")
        cases.append({"user_id": r.user_id, "as_of_at": r.as_of_at.isoformat(),
                      "renewal_due_at": r.renewal_due_at.isoformat(), "features": feats,
                      "expected": adapter.predict(r.user_id, feats, {})})
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps({"model_id": adapter.model_id, "model_version": adapter.model_version,
                               "sha256": adapter.metadata["sha256"], "cases": cases}, indent=1), encoding="utf-8")
    print(f"wrote {OUT} ({len(cases)} cases)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir")
    main(ap.parse_args().data_dir)
