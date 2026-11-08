"""Revenue-to-date candidates: same ablation rule and auto-renew-ON report as ablation_round2.py.

    python -m ml.temporal_churn.ablation_revenue [--data-dir PATH]

Candidates (snapshots.REVENUE_GROUPS): cumulative net revenue up to as_of_at and revenue per subscribed day, both
computed from transactions dated <= as_of_at (point-in-time replacement for Adapty's current total_revenue_usd).
"""
from __future__ import annotations

import argparse

from ml.temporal_churn import ablation_round2 as A
from ml.temporal_churn import snapshots as S
from ml.temporal_churn.train import REPORT_DIR

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir")
    A.main(ap.parse_args().data_dir, candidate_groups=S.REVENUE_GROUPS, stem="ablation_revenue",
           title="Revenue-to-date candidate features")
    print(open(REPORT_DIR / "ablation_revenue.md", encoding="utf-8").read())
