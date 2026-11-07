import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from shared.contracts.models import RetentionPlanRequest
from services.inference.app.economics import break_even, make_plan
from services.inference.app.main import app


@pytest.mark.parametrize("d", [0.10, 0.20, 0.30])
def test_break_even_identity(d):
    churn = 0.6
    threshold = break_even(churn, d)
    assert threshold.min_post_offer_renewal_probability == pytest.approx(0.4 / (1-d))
    assert threshold.required_absolute_uplift == pytest.approx(0.4*d/(1-d))
    assert (1-d) * threshold.min_post_offer_renewal_probability == pytest.approx(0.4)


def test_break_even_infeasible_when_renewal_probability_already_high():
    assert not break_even(0.1, 0.3).feasible_in_principle
    assert break_even(1.0, 0.3).feasible_in_principle


def req(budget=10.0, seed=42):
    return RetentionPlanRequest(
        app_id="lumen", experiment_id="experiment-123", budget_usd=budget,
        control_share=0.25, random_seed=seed,
        candidates=[
            {"user_id": f"user-{i:02d}", "churn_probability": x,
             "renewal_price_usd": 9.99 if i%2 else 4.99,
             "plan_type": "monthly" if i%2 else "weekly"}
            for i,x in enumerate([0.8,0.4,0.6,0.2,0.7,0.9,0.1,0.5])
        ],
    )


def test_plan_budget_random_control_and_no_uplift():
    plan = make_plan(req())
    assert plan.modeled_discount_uplift is False
    assert plan.plan_source == "scenario_experiment"
    assert plan.max_allocated_discount_exposure_usd <= plan.budget_usd
    assert plan.max_allocated_discount_exposure_usd + plan.unallocated_budget_usd == pytest.approx(10.0)
    assert any(a.arm == "control" for a in plan.assignments)
    assert len(set(a.user_id for a in plan.assignments)) == 8
    assert plan.expected_baseline_revenue_at_risk_usd > 0
    assert "no observed" in plan.disclaimer.lower()
    for a in plan.assignments:
        if a.arm.startswith("discount_"):
            assert a.min_post_offer_renewal_probability <= 1 + 1e-12
            assert a.required_absolute_uplift >= 0
        else:
            assert a.max_discount_exposure_usd == 0


def test_plan_is_deterministic_for_same_seed():
    a,b = make_plan(req()), make_plan(req())
    assert [x.model_dump() for x in a.assignments] == [x.model_dump() for x in b.assignments]
    assert a.request_fingerprint == b.request_fingerprint
    assert len(a.request_fingerprint) == 64


def test_zero_budget_has_no_discounted_arm():
    plan = make_plan(req(budget=0))
    assert plan.max_allocated_discount_exposure_usd == 0
    assert all(not a.arm.startswith("discount_") for a in plan.assignments)


def test_duplicate_customers_rejected():
    item = {"user_id":"dupe", "churn_probability":0.5,"renewal_price_usd":10,"plan_type":"monthly"}
    with pytest.raises(ValidationError):
        RetentionPlanRequest(app_id="x",experiment_id="dup",budget_usd=4,candidates=[item,item])


def test_invalid_discount_rejected():
    with pytest.raises(ValidationError):
        RetentionPlanRequest(app_id="x",experiment_id="dup",budget_usd=4,discounts=[1.1],candidates=[
            {"user_id":"x", "churn_probability":0.5,"renewal_price_usd":10,"plan_type":"monthly"}])


def test_plan_endpoint_no_persistence_in_unit_tests(monkeypatch):
    monkeypatch.delenv("ANALYTICS_URL", raising=False)
    response = TestClient(app).post("/v1/retention/plan",json=req().model_dump(mode="json"))
    assert response.status_code == 200, response.text
    assert response.json()["modeled_discount_uplift"] is False
