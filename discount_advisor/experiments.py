"""The randomized A/B tests contained in the data (DATA, causal within the synthetic dataset).

The offline users carry an `ab_test` column: users in a test were randomly assigned to one of its flows (paywalls).
Because assignment is random, differences between arms are causal effects of the paywall change, unlike every other
comparison in this dataset. These tests change the offer's STRUCTURE (trial vs weekly first, adding a lifetime plan),
not the price, so they do not measure discount sensitivity.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import norm

from data import Dataset
from metrics import product_values, segment_baseline

# Control arm = the test's arm "A" in the seeder's catalog (seed_adapty.AB_TESTS).
CONTROL_ARM = {
    "Onboarding: annual trial vs weekly first": "onb_trial",
    "Main: 3 plans vs lifetime anchor (NA)": "main",
    "Settings: upgrade vs lifetime anchor": "settings",
}
BALANCE_CHECKS = {"iOS share": ("platform", "iOS"), "US share": ("country", "US"),
                  "organic share": ("acquisition_channel", "organic")}


def two_prop_test(k1: int, n1: int, k2: int, n2: int) -> tuple[float, float, float]:
    """Difference p2 - p1, its 95% (unpooled Wald) CI half-width, and the two-sided pooled z-test p-value."""
    p1, p2 = k1 / n1, k2 / n2
    diff = p2 - p1
    half = 1.96 * np.sqrt(p1 * (1 - p1) / n1 + p2 * (1 - p2) / n2)
    pool = (k1 + k2) / (n1 + n2)
    se = np.sqrt(pool * (1 - pool) * (1 / n1 + 1 / n2))
    p = float(2 * norm.sf(abs(diff) / se)) if se > 0 else 1.0
    return float(diff), float(half), p


def arm_results(ds: Dataset, horizon_months: int = 12) -> pd.DataFrame:
    """One row per (test, arm): measured outcomes plus lift vs the control arm."""
    sv = product_values(ds, horizon_months)
    u = ds.users
    rows = []
    for test, control in CONTROL_ARM.items():
        in_test = u.ab_test == test
        if not in_test.any():
            continue
        arms = [control] + sorted(set(u.loc[in_test, "flow"]) - {control})
        base = None
        for arm in arms:
            m = in_test & (u.flow == arm)
            b = segment_baseline(ds, m, arm, horizon_months, sv)
            row = {"test": test, "arm": arm, "role": "control" if arm == control else "variant",
                   "placement": u.loc[m, "placement"].iloc[0], "installs": b.installs, "payers": b.payers,
                   "conversion": b.conversion, "conv_ci_low": b.conversion_ci[0], "conv_ci_high": b.conversion_ci[1],
                   "revenue_per_payer": b.value_per_converter, "revenue_per_install": b.revenue_per_install,
                   "cash_per_install": b.observed_net_per_payer * b.conversion,
                   "extrapolated_share": b.v0_split.get("extrapolated_tail", 0.0),
                   "plan_mix": ", ".join(f"{p} {v:.0%}" for p, v in b.product_mix.items())}
            for label, (col, val) in BALANCE_CHECKS.items():
                row[label] = float((u.loc[m, col] == val).mean())
            if base is None:
                base = row
                row.update(conv_lift=0.0, conv_diff=0.0, conv_diff_ci=0.0, p_value=np.nan,
                           revenue_lift=0.0, cash_lift=0.0)
            else:
                diff, half, p = two_prop_test(base["payers"], base["installs"], b.payers, b.installs)
                row.update(conv_lift=b.conversion / base["conversion"] - 1, conv_diff=diff, conv_diff_ci=half,
                           p_value=p, revenue_lift=b.revenue_per_install / base["revenue_per_install"] - 1,
                           cash_lift=row["cash_per_install"] / base["cash_per_install"] - 1)
            rows.append(row)
    return pd.DataFrame(rows)


def max_imbalance(arms: pd.DataFrame) -> float:
    """Largest gap between arms of the same test on any balance check (randomization sanity check)."""
    gaps = [arms.groupby("test")[c].agg(lambda s: s.max() - s.min()).max() for c in BALANCE_CHECKS]
    return float(max(gaps))


def mixed_flows(ds: Dataset, mask: pd.Series) -> pd.Series:
    """Paywall flows inside an audience (share of installs); more than one means the baseline is a blend."""
    return ds.users.loc[mask, "flow"].value_counts(normalize=True)
