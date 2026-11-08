"""Retention offers tab, driven headlessly with Streamlit's AppTest.

The analytics response is stubbed (the PostgreSQL path is covered by tests/test_retention_offers.py at the repo root).
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import retention_offers as R

APP = str(Path(__file__).resolve().parent.parent / "app.py")
T0 = datetime(2026, 11, 2, 12, tzinfo=timezone.utc)
SUBS = [("u1", 0.72, 6.99, "weekly", 1), ("u2", 0.35, 19.99, "monthly", 9), ("u3", 0.12, 6.99, "weekly", 2),
        ("u4", 0.55, 19.99, None, 4)]
PAYLOAD = {"model_id": R.MODEL_ID, "model_version": None, "reference_time": T0.isoformat(), "max_age_days": 7.0,
           "counts": {"subscribers_with_predictions": 6, "renewal_already_due": 1, "stale": 1, "eligible": 4,
                      "returned": 4},
           "subscribers": [{"prediction_id": u, "app_id": "lumen", "user_id": u, "model_version": "1.0.0",
                            "plan_type": plan, "predicted_at": T0.isoformat(), "as_of_at": T0.isoformat(),
                            "renewal_due_at": (T0 + timedelta(days=days)).isoformat(), "churn_probability": p,
                            "renewal_price_usd": price} for u, p, price, plan, days in SUBS]}


def _tab_only():
    import retention_tab
    retention_tab.render()


def _texts(at):
    return " ".join(str(x.value) for x in list(at.markdown) + list(at.caption) + list(at.info) + list(at.error)
                    + list(at.warning) + list(at.success))


@pytest.fixture
def stubbed(monkeypatch):
    import retention_tab
    retention_tab._load.clear()
    calls = []
    monkeypatch.setattr(R, "fetch_at_risk", lambda *a, **k: calls.append(k) or PAYLOAD)
    yield calls
    retention_tab._load.clear()


def test_tab_shows_risk_exposure_scenarios_and_experiment(stubbed):
    at = AppTest.from_function(_tab_only, default_timeout=60).run()
    assert not at.exception, [e.value for e in at.exception]
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Subscribers"] == "4"
    risk = sum(R.cents(p * price) / 100 for _, p, price, _, _ in SUBS)
    assert metrics["Expected revenue at risk"] == f"${risk:,.2f}"
    assert len(at.dataframe) >= 4            # subscribers, exposure, scenarios, arms
    t = _texts(at)
    assert "No observed discount-response data" in t
    assert "1 subscriber(s) left out: plan type unknown" in t
    assert "can break even" in t and "Randomized allocation preview" in t
    for claim in ("the optimal discount is", "best discount", "will increase", "expected uplift", "guaranteed to"):
        assert claim not in t.lower()

    at.slider(key="ro_minp").set_value(0.5).run()          # filters apply
    assert not at.exception
    assert {m.label: m.value for m in at.metric}["Subscribers"] == "2"

    at.multiselect(key="ro_discounts").set_value([]).run()  # no discount -> a message, not a crash
    assert not at.exception and "Pick at least one discount." in _texts(at)


def test_register_button_reports_service_failure_cleanly(stubbed, monkeypatch):
    def down(*a, **k):
        raise R.ServiceError("Inference /v1/retention/plan: cannot reach the service (ConnectError).")
    monkeypatch.setattr(R, "register_plan", down)
    at = AppTest.from_function(_tab_only, default_timeout=60).run()
    at.button(key="ro_register").click().run()
    assert not at.exception
    assert any("cannot reach the service" in e.value for e in at.error)


def test_register_button_calls_the_planner_api(stubbed, monkeypatch):
    sent = []

    def ok(req, url=None, client=None):
        sent.append(req)
        return R.preview_plan(req).model_dump(mode="json")
    monkeypatch.setattr(R, "register_plan", ok)
    at = AppTest.from_function(_tab_only, default_timeout=60).run()
    at.button(key="ro_register").click().run()
    assert not at.exception
    assert len(sent) == 1 and {c.user_id for c in sent[0].candidates} == {"u1", "u2", "u3"}
    assert any("matches the preview" in s.value for s in at.success)


def test_full_app_with_services_down_keeps_acquisition_tabs_working():
    import retention_tab
    retention_tab._load.clear()
    at = AppTest.from_file(APP, default_timeout=300).run()
    at.text_input(key="ro_analytics").set_value("http://127.0.0.1:9").run()
    assert not at.exception, [e.value for e in at.exception]
    t = _texts(at)
    assert "Could not load predictions" in t
    assert "Worth testing:" in t or "Keep full price" in t   # the acquisition recommendation still renders
