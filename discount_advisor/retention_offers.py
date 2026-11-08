"""Retention offers: existing subscribers at risk of not renewing, and which renewal discounts are worth *testing*.

Data flow (reuses the existing services and calculations, nothing new is modeled here):
  analytics  GET  /v1/retention/at-risk   latest valid CatBoost prediction per subscriber, read from PostgreSQL
  planner    services.inference.app.economics.break_even / make_plan   (same code as POST /v1/retention/plan)
  inference  POST /v1/retention/plan      registers a randomized experiment (persisted by analytics)
  sizing     economics.ab_sample_size     (the Discount Advisor's two-proportion test)

There is NO observed discount-response data. Break-even numbers are arithmetic thresholds a discount would have to
reach; they are not predictions that it will. Nothing here selects an "optimal" discount.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.append(str(_REPO))  # appended, so discount_advisor's own modules keep priority

from economics import ab_sample_size

from services.inference.app.economics import break_even, cents, make_plan
from shared.contracts.models import RetentionCandidate, RetentionPlanRequest, RetentionPlanResult

MODEL_ID = "lumen-temporal-catboost"
DEFAULT_ANALYTICS_URL = os.getenv("ANALYTICS_URL", "http://127.0.0.1:8002")
DEFAULT_INFERENCE_URL = os.getenv("INFERENCE_URL", "http://127.0.0.1:8001")
DEFAULT_DISCOUNTS = (0.10, 0.20, 0.30)
RISK_BANDS = [0.0, 0.1, 0.2, 0.3, 0.5, 1.0000001]
RISK_LABELS = ["<10%", "10–20%", "20–30%", "30–50%", "≥50%"]
RENEWAL_WINDOWS = [0, 1, 3, 7, 14, np.inf]
RENEWAL_LABELS = ["≤1 day", "1–3 days", "3–7 days", "7–14 days", ">14 days"]
DISCLAIMER = ("No observed discount-response data: these are break-even thresholds and a randomized test design, "
              "not predicted uplift, an optimal discount or guaranteed revenue.")


class ServiceError(RuntimeError):
    """A service could not be reached or returned an error; the message is safe to show in the UI."""


def _client(base_url: str, client=None):
    if client is not None:
        return client
    import httpx
    return httpx.Client(base_url=base_url, timeout=15)


def _call(fn, what: str):
    import httpx
    try:
        res = fn()
    except httpx.HTTPError as exc:
        raise ServiceError(f"{what}: cannot reach the service ({type(exc).__name__}).") from exc
    if res.status_code >= 400:
        raise ServiceError(f"{what}: HTTP {res.status_code} {res.text[:300]}")
    return res.json()


# ---------------------------------------------------------------- 1. data from PostgreSQL (via analytics)
def fetch_at_risk(analytics_url: str = DEFAULT_ANALYTICS_URL, *, model_id: str = MODEL_ID, app_id: str | None = None,
                  model_version: str | None = None, as_of: pd.Timestamp | None = None, max_age_days: float = 7,
                  limit: int = 5000, client=None) -> dict:
    params = {"model_id": model_id, "max_age_days": max_age_days, "limit": limit}
    if app_id:
        params["app_id"] = app_id
    if model_version:
        params["model_version"] = model_version
    if as_of is not None:
        params["as_of"] = pd.Timestamp(as_of).isoformat()
    c = _client(analytics_url, client)
    return _call(lambda: c.get("/v1/retention/at-risk", params=params), "Analytics /v1/retention/at-risk")


COLUMNS = ["user_id", "app_id", "plan_type", "churn_probability", "renewal_price_usd", "revenue_at_risk_usd",
           "renewal_due_at", "days_until_renewal", "as_of_at", "model_version", "prediction_id"]


def subscribers_frame(payload: dict) -> pd.DataFrame:
    """One row per subscriber. revenue_at_risk_usd = churn_probability × renewal_price_usd, rounded to cents exactly
    like the planner (`expected_revenue_at_risk_usd`)."""
    df = pd.DataFrame(payload.get("subscribers", []))
    if df.empty:
        return pd.DataFrame(columns=COLUMNS)
    for col in ("renewal_due_at", "as_of_at", "predicted_at"):
        df[col] = pd.to_datetime(df[col], utc=True)
    ref = pd.Timestamp(payload["reference_time"])
    df["revenue_at_risk_usd"] = [cents(price * p) / 100 for p, price in
                                 zip(df["churn_probability"], df["renewal_price_usd"])]
    df["days_until_renewal"] = (df["renewal_due_at"] - ref).dt.total_seconds() / 86400
    return df[COLUMNS].sort_values(["revenue_at_risk_usd", "user_id"], ascending=[False, True]).reset_index(drop=True)


# ---------------------------------------------------------------- 2. revenue exposure
def exposure(df: pd.DataFrame) -> dict:
    p, price = df["churn_probability"], df["renewal_price_usd"]
    return {"subscribers": len(df), "renewal_revenue_due_usd": float(price.sum()),
            "revenue_at_risk_usd": float(df["revenue_at_risk_usd"].sum()),
            "expected_renewals": float((1 - p).sum()), "expected_non_renewals": float(p.sum()),
            "mean_churn_probability": float(p.mean()) if len(df) else float("nan")}


def exposure_by(df: pd.DataFrame, by: str) -> pd.DataFrame:
    """by = 'risk' (churn-probability band), 'renewal' (days until renewal) or 'plan'."""
    d = df.copy()
    if by == "risk":
        d["group"] = pd.cut(d["churn_probability"], RISK_BANDS, labels=RISK_LABELS, right=False)
    elif by == "renewal":
        d["group"] = pd.cut(d["days_until_renewal"], RENEWAL_WINDOWS, labels=RENEWAL_LABELS, right=True)
    elif by == "plan":
        d["group"] = d["plan_type"].fillna("unknown")
    else:
        raise ValueError(by)
    g = d.groupby("group", observed=False)
    out = pd.DataFrame({"subscribers": g.size(), "renewal_revenue_due_usd": g["renewal_price_usd"].sum(),
                        "revenue_at_risk_usd": g["revenue_at_risk_usd"].sum(),
                        "mean_churn_probability": g["churn_probability"].mean()})
    out["share_of_revenue_at_risk"] = out["revenue_at_risk_usd"] / max(out["revenue_at_risk_usd"].sum(), 1e-12)
    return out.reset_index().rename(columns={"group": by})


# ---------------------------------------------------------------- 3. discount scenarios (break-even only)
def break_even_table(df: pd.DataFrame, discount: float) -> pd.DataFrame:
    """Per subscriber: the planner's break_even() for one discount offered on the next renewal."""
    rows = [break_even(float(p), discount) for p in df["churn_probability"]]
    return pd.DataFrame({
        "user_id": df["user_id"].to_numpy(),
        "baseline_renewal_probability": [r.baseline_renewal_probability for r in rows],
        "min_post_offer_renewal_probability": [r.min_post_offer_renewal_probability for r in rows],
        "required_absolute_uplift": [r.required_absolute_uplift for r in rows],
        "feasible_in_principle": [r.feasible_in_principle for r in rows],
    })


def discount_scenarios(df: pd.DataFrame, discounts=DEFAULT_DISCOUNTS, control_share: float = 0.2) -> pd.DataFrame:
    """For each discount, offered to every subscriber in `df` on their next renewal:

    - can break even = the planner's feasibility (renewal needed ≤ 100%, i.e. churn probability ≥ discount);
    - renewal needed = baseline renewal ÷ (1 − d): the same +d/(1−d) relative improvement for everyone;
    - discount cost on renewers who'd renew anyway = Σ (1 − p) × price × d, which is exactly the revenue extra renewals
      would have to win back;
    - users per arm = two-proportion test (α 0.05 Bonferroni-split across arms, power 0.8) able to detect a change of
      exactly the break-even size among the subscribers who can break even.

    Revenue figures are face value (before store fee); a renewal discount here applies to one payment.
    """
    rows = []
    n_arms = len(discounts)
    for d in sorted(discounts):
        be = break_even_table(df, d)
        ok = be["feasible_in_principle"].to_numpy()
        sub, sub_be = df[ok], be[ok]
        base = float(sub_be["baseline_renewal_probability"].mean()) if ok.any() else float("nan")
        rel = 1 / (1 - d) - 1
        n_arm = ab_sample_size(base, rel, comparisons=n_arms) if ok.any() else 0
        per_arm_available = ok.sum() * (1 - control_share) / n_arms
        rows.append({
            "discount": d,
            "subscribers": len(df),
            "can_break_even": int(ok.sum()),
            "baseline_renewal_rate": base,
            "renewal_rate_needed": float(sub_be["min_post_offer_renewal_probability"].mean()) if ok.any() else np.nan,
            "relative_improvement_needed": rel,
            "extra_renewals_needed": float(sub_be["required_absolute_uplift"].sum()),
            "revenue_at_risk_usd": float(sub["revenue_at_risk_usd"].sum()),
            "discount_cost_on_baseline_renewers_usd": float(
                ((1 - sub["churn_probability"]) * sub["renewal_price_usd"] * d).sum()),
            "users_per_arm_to_detect": int(n_arm),
            "users_per_arm_available": float(per_arm_available),
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- 4. experiment (existing planner)
def plan_request(df: pd.DataFrame, *, app_id: str, experiment_id: str, budget_usd: float,
                 control_share: float = 0.2, discounts=DEFAULT_DISCOUNTS, random_seed: int = 42
                 ) -> tuple[RetentionPlanRequest, int]:
    """RetentionPlanRequest for the subscribers in `df` that have a known weekly/monthly plan.
    Returns (request, number of subscribers left out because their plan_type is unknown)."""
    known = df[df["plan_type"].isin(["weekly", "monthly"])]
    if known.empty:
        raise ValueError("No subscribers with a known weekly/monthly plan_type to plan an experiment for.")
    candidates = [RetentionCandidate(user_id=r.user_id, churn_probability=float(r.churn_probability),
                                     renewal_price_usd=float(r.renewal_price_usd), plan_type=r.plan_type)
                  for r in known.itertuples(index=False)]
    req = RetentionPlanRequest(app_id=app_id, experiment_id=experiment_id, budget_usd=budget_usd,
                               control_share=control_share, discounts=list(discounts), random_seed=random_seed,
                               candidates=candidates)
    return req, int(len(df) - len(known))


def preview_plan(req: RetentionPlanRequest) -> RetentionPlanResult:
    """The planner itself, run locally: identical to what POST /v1/retention/plan returns (same fingerprint),
    but nothing is stored."""
    return make_plan(req)


def register_plan(req: RetentionPlanRequest, inference_url: str = DEFAULT_INFERENCE_URL, client=None) -> dict:
    """POST /v1/retention/plan: the inference service plans it and analytics stores it (immutable per experiment_id)."""
    c = _client(inference_url, client)
    return _call(lambda: c.post("/v1/retention/plan", json=req.model_dump(mode="json")),
                 "Inference /v1/retention/plan")


def arm_summary(result: RetentionPlanResult) -> pd.DataFrame:
    a = pd.DataFrame([x.model_dump() for x in result.assignments])
    g = a.groupby("arm")
    out = pd.DataFrame({"subscribers": g.size(),
                        "revenue_at_risk_usd": g["expected_revenue_at_risk_usd"].sum(),
                        "max_discount_exposure_usd": g["max_discount_exposure_usd"].sum(),
                        "mean_baseline_renewal": g["baseline_renewal_probability"].mean(),
                        "mean_renewal_needed": g["min_post_offer_renewal_probability"].mean()})
    return out.reset_index()


def recommendations(scenarios: pd.DataFrame, result: RetentionPlanResult | None = None) -> list[str]:
    """Plain-language experiment advice. Says what a test can detect; never which discount will win."""
    out = []
    for r in scenarios.itertuples(index=False):
        d = f"{r.discount:.0%}"
        if r.can_break_even == 0:
            out.append(f"**{d}:** no subscriber here can break even (each would need a renewal rate above 100%). "
                       "Don't test it on this group.")
            continue
        head = (f"**{d}:** {r.can_break_even} of {r.subscribers} subscribers can break even; renewal must rise "
                f"from {r.baseline_renewal_rate:.1%} to {r.renewal_rate_needed:.1%} "
                f"(+{r.relative_improvement_needed:.0%} relative) just to recover the discount.")
        if r.users_per_arm_to_detect == 0:
            out.append(head + " A break-even change is not measurable here (needed rate ≥ 100%).")
        elif r.users_per_arm_available >= r.users_per_arm_to_detect:
            out.append(head + f" Testable now: ~{r.users_per_arm_available:.0f} per arm available, "
                              f"{r.users_per_arm_to_detect:,} needed.")
        else:
            cycles = int(np.ceil(r.users_per_arm_to_detect / max(r.users_per_arm_available, 1e-9)))
            out.append(head + f" Underpowered on one cohort: {r.users_per_arm_to_detect:,} per arm needed, "
                              f"~{r.users_per_arm_available:.0f} available. Keep enrolling over about {cycles} "
                              "renewal cohorts like this one, or test fewer arms.")
    if result is not None:
        n_no = sum(a.arm == "no_offer" for a in result.assignments)
        if n_no:
            out.append(f"{n_no} subscriber(s) got **no offer**: no listed discount can break even for them or the "
                       "budget ran out. That is by design, not a prediction that they will renew.")
    out.append("Decide on the decision rule before launch (primary metric: renewal rate and net renewal revenue per "
               "subscriber vs control), and compare arms only with the randomized control.")
    return out
