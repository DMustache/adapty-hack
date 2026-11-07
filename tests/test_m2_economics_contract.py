"""Independent checks of the frozen M2 planning contract."""

import json
from collections import Counter
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from jsonschema import validate

from services.inference.app.economics import break_even, make_plan
from services.inference.app.main import app
from shared.contracts.models import RetentionPlanRequest

RESULT_SCHEMA = json.loads(
    (Path(__file__).resolve().parents[1] / "contracts/schemas/retention-plan-result.schema.json").read_text()
)


def candidate(user_id, churn=1.0, price=0.10):
    return {
        "user_id": user_id,
        "churn_probability": churn,
        "renewal_price_usd": price,
        "plan_type": "monthly",
    }


def request(candidates, budget=1.0, discounts=None, control_share=0.0, seed=17):
    return RetentionPlanRequest(
        app_id="qa-app",
        experiment_id="qa-experiment",
        budget_usd=budget,
        control_share=control_share,
        discounts=[0.10, 0.20, 0.30] if discounts is None else discounts,
        random_seed=seed,
        candidates=candidates,
    )


def assert_assignments_cover_request(plan, candidates):
    expected = Counter(item["user_id"] for item in candidates)
    actual = Counter(item.user_id for item in plan.assignments)
    assert actual == expected
    assert all(count == 1 for count in actual.values())


def assert_budget_invariant(plan):
    exposure = sum(item.max_discount_exposure_usd for item in plan.assignments)
    assert exposure == pytest.approx(plan.max_allocated_discount_exposure_usd, abs=1e-9)
    assert exposure <= plan.budget_usd + 1e-9
    assert plan.unallocated_budget_usd >= -1e-9
    assert exposure + plan.unallocated_budget_usd == pytest.approx(plan.budget_usd, abs=1e-9)


@pytest.mark.parametrize("discount", [0.10, 0.20, 0.30])
def test_break_even_thresholds_at_probability_boundaries(discount):
    for churn in (0.0, discount, 1.0):
        result = break_even(churn, discount)
        baseline = 1 - churn
        expected_threshold = baseline / (1 - discount)
        assert result.min_post_offer_renewal_probability == pytest.approx(expected_threshold)
        assert result.required_absolute_uplift == pytest.approx(expected_threshold - baseline)
        assert result.feasible_in_principle is (churn >= discount)

    assert not break_even(discount / 2, discount).feasible_in_principle


@pytest.mark.parametrize("budget", [0.0, 0.009, 0.01])
def test_zero_and_cent_level_budgets(budget):
    candidates = [candidate("a"), candidate("b")]
    plan = make_plan(request(candidates, budget=budget, discounts=[0.10]))
    assert_assignments_cover_request(plan, candidates)
    assert_budget_invariant(plan)
    discounted = [item for item in plan.assignments if item.discount_fraction > 0]
    assert len(discounted) == (1 if budget == 0.01 else 0)
    assert all(item.arm == "no_offer" for item in plan.assignments if item not in discounted)


@pytest.mark.parametrize("discount", [0.10, 0.20, 0.30])
def test_infeasible_candidates_are_never_offered_discounts(discount):
    candidates = [candidate("infeasible", churn=discount / 2), candidate("feasible", churn=1.0)]
    plan = make_plan(request(candidates, discounts=[discount]))
    assert_assignments_cover_request(plan, candidates)
    assert_budget_invariant(plan)
    by_user = {item.user_id: item for item in plan.assignments}
    assert by_user["infeasible"].arm == "no_offer"
    assert by_user["infeasible"].discount_fraction == 0
    assert by_user["infeasible"].max_discount_exposure_usd == 0
    assert by_user["feasible"].discount_fraction == pytest.approx(discount)


def test_seeded_control_and_complete_assignments():
    candidates = [candidate(f"user-{i:02d}", churn=0.8, price=4.99) for i in range(20)]
    payload = request(candidates, budget=100, control_share=0.25)
    first, second = make_plan(payload), make_plan(payload)
    assert_assignments_cover_request(first, candidates)
    assert_budget_invariant(first)
    assert [a.model_dump() for a in first.assignments] == [a.model_dump() for a in second.assignments]
    assert first.request_fingerprint == second.request_fingerprint
    controls = [item for item in first.assignments if item.arm == "control"]
    assert controls
    assert all(item.discount_fraction == 0 and item.max_discount_exposure_usd == 0 for item in controls)


def test_http_plan_matches_schema_and_disclaims_treatment_effect(monkeypatch):
    monkeypatch.delenv("ANALYTICS_URL", raising=False)
    candidates = [candidate("a", churn=0.0), candidate("b", churn=1.0)]
    payload = request(candidates, budget=0.01, discounts=[0.10])
    client = TestClient(app)
    first = client.post("/v1/retention/plan", json=payload.model_dump(mode="json"))
    second = client.post("/v1/retention/plan", json=payload.model_dump(mode="json"))
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    body = first.json()
    validate(body, RESULT_SCHEMA)
    assert body["plan_source"] == "scenario_experiment"
    assert body["modeled_discount_uplift"] is False
    assert body["disclaimer"].strip()
    assert "no observed" in body["disclaimer"].lower()
    assert not {"measured_uplift", "observed_savings_usd", "optimized_savings_usd"} & body.keys()
    assert body["assignments"] == second.json()["assignments"]
    assert body["request_fingerprint"] == second.json()["request_fingerprint"]
    assert Counter(item["user_id"] for item in body["assignments"]) == Counter(
        item["user_id"] for item in candidates
    )
    assert sum(item["max_discount_exposure_usd"] for item in body["assignments"]) <= 0.01 + 1e-9
    assert next(item for item in body["assignments"] if item["user_id"] == "a")["arm"] == "no_offer"
