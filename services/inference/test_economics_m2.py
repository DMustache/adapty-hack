"""M2 planner regressions kept with the backend-owned source."""

import pytest

from services.inference.app.economics import break_even, make_plan
from shared.contracts.models import RetentionPlanRequest


@pytest.mark.parametrize("discount", [0.1, 0.2, 0.3])
def test_break_even_threshold_and_feasibility_boundary(discount):
    at_boundary = break_even(discount, discount)
    assert at_boundary.min_post_offer_renewal_probability == 1
    assert at_boundary.feasible_in_principle is True
    assert break_even(1, discount).min_post_offer_renewal_probability == 0
    assert break_even(0, discount).feasible_in_principle is False

    just_below = break_even(discount - 1e-13, discount)
    assert just_below.min_post_offer_renewal_probability > 1
    assert just_below.feasible_in_principle is False


def request(*, budget, price, churn=1, discounts=None, control_share=0):
    return RetentionPlanRequest(
        app_id="app", experiment_id="experiment", budget_usd=budget,
        control_share=control_share, random_seed=7,
        discounts=discounts or [0.1],
        candidates=[
            {"user_id": "u1", "churn_probability": churn,
             "renewal_price_usd": price, "plan_type": "weekly"},
        ],
    )


def test_fractional_cent_exposure_does_not_create_free_discount():
    plan = make_plan(request(budget=0, price=0.04))
    assert plan.assignments[0].arm == "no_offer"
    assert plan.max_allocated_discount_exposure_usd == 0

    plan = make_plan(request(budget=0.01, price=0.04))
    assert plan.assignments[0].arm == "discount_10pct"
    assert plan.assignments[0].max_discount_exposure_usd == 0.01


def test_fractional_cent_budget_cannot_be_rounded_up():
    plan = make_plan(request(budget=0.005, price=0.10))
    assert plan.assignments[0].arm == "no_offer"
    assert plan.max_allocated_discount_exposure_usd <= plan.budget_usd
    assert plan.unallocated_budget_usd == 0.005

    plan = make_plan(request(budget=0.019, price=0.10))
    assert plan.assignments[0].arm == "discount_10pct"
    assert plan.max_allocated_discount_exposure_usd == 0.01
    assert plan.unallocated_budget_usd == 0.009


def test_infeasible_candidate_is_assigned_once_without_discount():
    plan = make_plan(request(budget=100, price=10, churn=0.2, discounts=[0.3]))
    assert [a.user_id for a in plan.assignments] == ["u1"]
    assert plan.assignments[0].arm == "no_offer"
    assert plan.max_allocated_discount_exposure_usd == 0
