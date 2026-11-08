"""Opt-in checks of the stored-prediction to planner bridge on the running stack."""
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

pytestmark = pytest.mark.skipif(os.getenv("M7_QA_INTEGRATION") != "1", reason="requires M7 Compose stack")
ROOT = Path(__file__).resolve().parents[1]
ANA = os.getenv("ANALYTICS_URL", "http://127.0.0.1:8002")
INF = os.getenv("INFERENCE_URL", "http://127.0.0.1:8001")


def http(method, url, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as response:
        return json.load(response)


def query(path, **params):
    return http("GET", ANA + path + "?" + urllib.parse.urlencode(params))


def test_fixed_model_plan_propagation_and_conflict():
    case = json.loads((ROOT / "tests/fixtures/temporal_churn_fixture.json").read_text())["cases"][0]
    run = uuid4().hex
    request = {"request_id": f"m7-{run}", "app_id": f"m7-{run}", "user_id": f"synthetic-{run}",
               "model_id": "lumen-temporal-catboost", "renewal_horizon_days": 7,
               "context": {"as_of_at": case["as_of_at"], "renewal_due_at": case["renewal_due_at"]},
               "features": case["features"]}
    prediction = http("POST", INF + "/v1/predict", request)
    assert prediction["plan_type"] == case["features"]["plan"]
    stored = http("GET", ANA + "/v1/predictions/" + prediction["prediction_id"])
    assert stored["plan_type"] == prediction["plan_type"]
    opposite = "monthly" if prediction["plan_type"] == "weekly" else "weekly"
    with pytest.raises(urllib.error.HTTPError) as err:
        http("POST", INF + "/v1/predict", {**request, "request_id": f"bad-{run}", "plan_type": opposite})
    assert err.value.code == 422


def test_cutoff_latest_due_stale_and_planner_bridge():
    run = uuid4().hex
    app = f"m7-{run}"
    t = datetime.now(UTC).replace(microsecond=0)
    day = timedelta(days=1)

    def ingest(user, cutoff, due, probability, *, plan="weekly", predicted=None, price=10.0,
               app_id=app, version="1.0.0"):
        payload = {"prediction_id": str(uuid4()), "request_id": str(uuid4()), "app_id": app_id,
                   "user_id": user, "model_id": "lumen-temporal-catboost", "model_version": version,
                   "prediction_source": "external", "predicted_at": (predicted or cutoff).isoformat(),
                   "renewal_horizon_days": 7, "churn_probability": probability,
                   "as_of_at": cutoff.isoformat(), "renewal_due_at": due.isoformat(),
                   "renewal_price_usd": price, "plan_type": plan}
        assert http("POST", ANA + "/v1/ingest/predictions", payload)["status"] == "stored"
        return payload

    ingest("latest", t - 2 * day, t + 2 * day, 0.9)
    latest = ingest("latest", t - day, t + 2 * day, 0.2, plan="monthly")
    ingest("due", t - 2 * day, t + 2 * day, 0.3)
    ingest("due", t - day, t - day / 2, 0.8)
    ingest("stale", t - 10 * day, t + 2 * day, 0.7, predicted=t)
    ingest("missing", t, t + day, 0.6, plan=None)
    ingest("future", t, t + day, 0.95, predicted=t + day)
    ingest("eligible", t, t + day, 0.75)
    ingest("other-app", t, t + day, 0.99, app_id=f"other-{run}")
    ingest("other-version", t, t + day, 0.99, version="0.9.0")
    out = query("/v1/retention/at-risk", app_id=app, as_of=t.isoformat())
    assert {row["user_id"] for row in out["subscribers"]} == {"latest", "eligible"}
    assert out["counts"] == {"subscribers_with_predictions": 5, "renewal_already_due": 1,
                             "stale": 1, "missing_plan_type": 1, "eligible": 2, "returned": 2}
    assert out["subscribers"][0]["user_id"] == "eligible"
    assert out["subscribers"][1]["prediction_id"] == latest["prediction_id"]
    assert all(row["prediction_source"] == "external" for row in out["subscribers"])
    assert len(query("/v1/retention/at-risk", app_id=app, as_of=t.isoformat(), limit=1)["subscribers"]) == 1
    request = {"app_id": app, "experiment_id": f"m7-{run}", "budget_usd": 10,
               "candidates": [{key: row[key] for key in ("user_id", "plan_type", "churn_probability",
                                                          "renewal_price_usd")} for row in out["subscribers"]]}
    plan = http("POST", INF + "/v1/retention/plan", request)
    assert {row["user_id"] for row in plan["assignments"]} == {"latest", "eligible"}
    assert plan["modeled_discount_uplift"] is False
    assert http("POST", ANA + "/v1/ingest/predictions", latest)["status"] == "duplicate"
    with pytest.raises(urllib.error.HTTPError) as err:
        http("POST", ANA + "/v1/ingest/predictions", {**latest, "plan_type": "weekly"})
    assert err.value.code == 409


def test_reference_must_be_utc_and_app_is_required():
    for params in ({"app_id": "lumen", "as_of": "2026-10-30T12:00:00"},
                   {"app_id": "lumen", "as_of": "2026-10-30T12:00:00+02:00"},
                   {"app_id": "lumen", "max_age_days": 0},
                   {"app_id": "lumen", "limit": 0}, {}):
        with pytest.raises(urllib.error.HTTPError) as err:
            query("/v1/retention/at-risk", **params)
        assert err.value.code == 422
