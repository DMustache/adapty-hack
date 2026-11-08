"""Opt-in checks against the running M5 Compose stack on the gated develop SHA."""

import json
import os
import subprocess
import urllib.request
from pathlib import Path
from uuid import uuid4

import pytest

pytestmark = pytest.mark.skipif(os.getenv("M5_QA_INTEGRATION") != "1", reason="requires running M5 Compose stack")
ROOT = Path(__file__).resolve().parents[1]
INF = os.getenv("INFERENCE_URL", "http://127.0.0.1:8001")
ANA = os.getenv("ANALYTICS_URL", "http://127.0.0.1:8002")


def http(method, url, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(url, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)


def psql(sql):
    result = subprocess.run(
        ["docker", "compose", "exec", "-T", "postgres", "psql", "-X", "-v", "ON_ERROR_STOP=1",
         "-U", "adapty_demo", "-d", "adapty_demo", "-At"],
        cwd=ROOT, input=sql, text=True, capture_output=True, check=True,
    )
    return result.stdout.strip()


def test_running_mock_and_fixed_fixture_have_distinct_provenance():
    run = uuid4().hex
    mock = http("POST", INF + "/v1/predict", {
        "request_id": f"m5-mock-{run}", "app_id": "lumen-demo", "user_id": f"synthetic-{run}",
        "model_id": "mock-churn-v1", "renewal_horizon_days": 30,
        "context": {"category": "photo_video"}, "features": {"event_count": 4},
    })
    fixture = json.loads((ROOT / "tests/fixtures/temporal_churn_fixture.json").read_text())
    case = fixture["cases"][0]
    fixed = http("POST", INF + "/v1/predict", {
        "schema_version": "1.0", "request_id": f"m5-fixed-{run}", "app_id": "lumen-demo",
        "user_id": f"synthetic-{run}", "model_id": fixture["model_id"],
        "renewal_horizon_days": 7,
        "context": {"as_of_at": case["as_of_at"], "renewal_due_at": case["renewal_due_at"]},
        "features": case["features"],
    })
    assert (mock["prediction_source"], fixed["prediction_source"]) == ("mock", "external")
    assert fixed["model_id"] == fixture["model_id"] and fixed["model_version"] == fixture["model_version"]
    assert fixed["churn_probability"] == pytest.approx(case["expected"], abs=1e-9)
    for prediction in (mock, fixed):
        saved = http("GET", ANA + "/v1/predictions/" + prediction["prediction_id"])
        assert (saved["model_id"], saved["model_version"], saved["prediction_source"]) == (
            prediction["model_id"], prediction["model_version"], prediction["prediction_source"])
    saved_fixed = http("GET", ANA + "/v1/predictions/" + fixed["prediction_id"])
    assert saved_fixed["as_of_at"] is not None and saved_fixed["renewal_due_at"] is not None
    assert saved_fixed["renewal_price_usd"] == case["features"]["renewal_price_usd"]


def test_existing_volume_migration_reruns_and_trajectory_is_read_only():
    schema = "qa_m5_" + uuid4().hex[:12]
    old_ddl = (ROOT / "postgres/init/001-schema.sql").read_text()
    migration = (ROOT / "postgres/init/003-temporal-predictions.sql").read_text()
    try:
        psql(f"CREATE SCHEMA {schema}; SET search_path TO {schema}, public;\n" + old_ddl)
        psql(f"SET search_path TO {schema}, public; "
             "INSERT INTO churn_predictions (prediction_id, request_id, app_id, user_id, model_id, "
             "model_version, prediction_source, predicted_at, renewal_horizon_days, churn_probability) "
             "VALUES ('old', 'old', 'lumen', 'pseudo-1', 'mock-churn-v1', '0.0.0-mock', "
             "'mock', '2026-10-01T00:00:00Z', 30, 0.25);")
        for _ in range(2):
            psql(f"SET search_path TO {schema}, public;\n" + migration)
        assert psql(f"SET search_path TO {schema}, public; "
                    "SELECT prediction_id || ':' || COALESCE(as_of_at::text, 'old') "
                    "FROM churn_risk_trajectory WHERE prediction_id = 'old';") == "old:old"
        rights = psql(f"SELECT has_table_privilege('grafana_ro', '{schema}.churn_risk_trajectory', 'SELECT'), "
                      f"has_table_privilege('grafana_ro', '{schema}.churn_risk_trajectory', 'INSERT');")
        assert rights == "t|f"
    finally:
        psql(f"DROP SCHEMA IF EXISTS {schema} CASCADE;")
