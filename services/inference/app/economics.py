"""Deterministic break-even arithmetic and budget-bounded experiment allocation.

NO estimate of discount treatment uplift or savings is made here.
"""
from datetime import datetime, timezone
import hashlib
import json
from decimal import Decimal, ROUND_HALF_UP
import random
from shared.contracts.models import (
    BreakEvenResult, ExperimentAssignment, RetentionPlanRequest, RetentionPlanResult,
)


def cents(value: float) -> int:
    return int((Decimal(str(value)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def break_even(churn_probability: float, discount_fraction: float) -> BreakEvenResult:
    if not 0 <= churn_probability <= 1:
        raise ValueError("churn_probability must be in [0,1]")
    if not 0 < discount_fraction < 1:
        raise ValueError("discount must be in (0,1)")
    p0 = 1.0 - churn_probability
    p_min = p0 / (1.0 - discount_fraction)
    return BreakEvenResult(
        baseline_renewal_probability=p0,
        discount_fraction=discount_fraction,
        min_post_offer_renewal_probability=p_min,
        required_absolute_uplift=p_min - p0,
        feasible_in_principle=p_min <= 1.0 + 1e-12,
    )


def make_plan(req: RetentionPlanRequest) -> RetentionPlanResult:
    """Randomized control + discounted arms, limited by *maximum* possible face-value discount.

    Eligibility means mathematically possible to break even; never an estimated positive ROI.
    """
    users = list(req.candidates)
    random.Random(req.random_seed).shuffle(users)
    n_control = round(len(users) * req.control_share)
    if req.control_share > 0 and len(users) >= 2:
        n_control = max(1, n_control)
    if len(users) > 1:
        n_control = min(n_control, len(users) - 1)
    remaining_cents = cents(req.budget_usd)
    allocated_cents = 0
    result = []
    discounts = sorted(req.discounts)
    for index, user in enumerate(users):
        baseline = 1.0 - user.churn_probability
        common = {"renewal_price_usd": user.renewal_price_usd,
                  "expected_revenue_at_risk_usd": cents(user.renewal_price_usd * user.churn_probability) / 100}
        if index < n_control:
            result.append(ExperimentAssignment(
                user_id=user.user_id, plan_type=user.plan_type, arm="control", discount_fraction=0,
                max_discount_exposure_usd=0, **common,
                baseline_renewal_probability=baseline,
            ))
            continue
        # Rotate candidate arms to avoid a single preferred tier being called "optimal".
        rotation = (index - n_control) % len(discounts)
        order = discounts[rotation:] + discounts[:rotation]
        selected = None
        for discount in order:
            evaluation = break_even(user.churn_probability, discount)
            exposure = cents(user.renewal_price_usd * discount)
            if evaluation.feasible_in_principle and exposure <= remaining_cents:
                selected = (discount, exposure, evaluation)
                break
        if selected is None:
            result.append(ExperimentAssignment(
                user_id=user.user_id, plan_type=user.plan_type, arm="no_offer", discount_fraction=0,
                max_discount_exposure_usd=0, **common,
                baseline_renewal_probability=baseline,
            ))
            continue
        discount, exposure, evaluation = selected
        remaining_cents -= exposure
        allocated_cents += exposure
        result.append(ExperimentAssignment(
            user_id=user.user_id, plan_type=user.plan_type,
            arm=f"discount_{round(discount * 100)}pct",
            discount_fraction=discount,
            max_discount_exposure_usd=exposure / 100, **common,
            baseline_renewal_probability=baseline,
            min_post_offer_renewal_probability=evaluation.min_post_offer_renewal_probability,
            required_absolute_uplift=evaluation.required_absolute_uplift,
        ))
    fingerprint = hashlib.sha256(json.dumps(
        req.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    ).encode()).hexdigest()
    return RetentionPlanResult(
        experiment_id=req.experiment_id, app_id=req.app_id, request_fingerprint=fingerprint,
        created_at=datetime.now(timezone.utc), budget_usd=req.budget_usd,
        max_allocated_discount_exposure_usd=allocated_cents / 100,
        expected_baseline_revenue_at_risk_usd=sum(cents(c.renewal_price_usd * c.churn_probability) for c in users) / 100,
        unallocated_budget_usd=remaining_cents / 100,
        assignments=result,
        disclaimer=(
            "Experiment allocation only. There are no observed discount treatment outcomes. "
            "Break-even thresholds are algebraic; allocation is randomized, not an uplift-optimized policy. "
            "Budget limits maximum face-value discount exposure, not realized cost or profit."
        ),
    )
