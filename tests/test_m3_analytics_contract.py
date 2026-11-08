"""M3 assertions derived from the frozen ingestion schemas and dashboard contract."""

import base64
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from jsonschema import validate

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "contracts" / "schemas"
BOARD = ROOT / "grafana" / "dashboards" / "smart-retention.json"
DATASOURCE = ROOT / "grafana" / "provisioning" / "datasources" / "postgres.yaml"


def prediction(suffix, source="mock"):
    return {
        "schema_version": "1.0", "prediction_id": f"m3-pred-{suffix}",
        "request_id": f"m3-req-{suffix}", "app_id": f"m3-app-{suffix}",
        "user_id": f"m3-user-{suffix}", "model_id": "qa-model",
        "model_version": "1.0", "prediction_source": source,
        "predicted_at": datetime.now(UTC).isoformat(),
        "renewal_horizon_days": 30, "churn_probability": 0.8,
    }


def experiment(suffix):
    return {
        "schema_version": "1.0", "experiment_id": f"m3-exp-{suffix}",
        "app_id": f"m3-app-{suffix}", "request_fingerprint": "a" * 64,
        "created_at": datetime.now(UTC).isoformat(),
        "plan_source": "scenario_experiment", "modeled_discount_uplift": False,
        "budget_usd": 10.0, "max_allocated_discount_exposure_usd": 1.0,
        "expected_baseline_revenue_at_risk_usd": 4.0, "unallocated_budget_usd": 9.0,
        "assignments": [{
            "user_id": f"m3-user-{suffix}", "plan_type": "monthly", "arm": "discount_10pct",
            "discount_fraction": 0.1, "max_discount_exposure_usd": 1.0,
            "renewal_price_usd": 10.0, "expected_revenue_at_risk_usd": 4.0,
            "baseline_renewal_probability": 0.6,
            "min_post_offer_renewal_probability": 2 / 3,
            "required_absolute_uplift": 1 / 15,
        }],
        "disclaimer": "Hypothetical experiment; no observed treatment effect or savings.",
    }


def actual(suffix):
    return {
        "observation_id": f"m3-actual-{suffix}", "app_id": f"m3-app-{suffix}",
        "metric_name": "renewals", "metric_value": 1.0,
        "observed_at": datetime.now(UTC).isoformat(),
        "dimensions": {"cohort": "qa"}, "source": "demo",
    }


def test_m3_payloads_follow_frozen_schemas():
    for name, value in (
        ("churn-prediction-result", prediction("schema")),
        ("retention-plan-result", experiment("schema")),
        ("actual-observation", actual("schema")),
    ):
        validate(value, json.loads((SCHEMAS / f"{name}.schema.json").read_text()))


def test_m3_datasource_and_current_dashboard_provisioning():
    board = json.loads(BOARD.read_text())
    datasource = DATASOURCE.read_text()
    assert board["timezone"].lower() == "utc"
    assert "type: postgres" in datasource
    assert "user: grafana_ro" in datasource
    assert "password: $GF_DB_READ_PASSWORD" in datasource
    panels = {panel["id"]: panel for panel in board["panels"]}
    assert {1, 2, 3, 4}.issubset(panels)
    assert all(panel["datasource"]["uid"] == "adapty-pg" for panel in panels.values())
    assert board["uid"] == "smart-retention"
    assert "offline" in board["title"].lower()
    for panel in panels.values():
        assert panel["targets"][0]["rawSql"].lstrip().lower().startswith("select ")
    labels = " ".join([board["title"], *[p["title"] for p in panels.values()]])
    assert "campaign" in labels.lower()
    assert "outcome measurement status" in labels.lower()
    assert "saved revenue" not in labels.lower()


def _psql(sql):
    command = [
        "docker", "compose", "exec", "-T", "postgres", "sh", "-c",
        'psql -X -q -t -A -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f -',
    ]
    result = subprocess.run(command, input=sql, text=True, capture_output=True, cwd=ROOT, check=True)
    return result.stdout.strip()


def _api(method, path, payload=None):
    url = os.getenv("M3_QA_ANALYTICS_URL", "http://127.0.0.1:8002") + path
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(url, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, json.load(error)


def _grafana_dashboard():
    env_file = {}
    if (ROOT / ".env").exists():
        for line in (ROOT / ".env").read_text().splitlines():
            key, sep, value = line.partition("=")
            if sep:
                env_file[key.strip()] = value.strip().strip('"').strip("'")
    user = os.getenv("GF_SECURITY_ADMIN_USER", env_file.get("GF_SECURITY_ADMIN_USER", "admin"))
    password = os.getenv("GF_SECURITY_ADMIN_PASSWORD", env_file.get("GF_SECURITY_ADMIN_PASSWORD", "admin_demo"))
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    url = os.getenv("M3_QA_GRAFANA_URL", "http://127.0.0.1:3000")
    request = urllib.request.Request(
        url + "/api/dashboards/uid/smart-retention",
        headers={"Authorization": f"Basic {token}"},
    )
    for attempt in range(40):
        try:
            with urllib.request.urlopen(request, timeout=8) as response:
                return json.load(response)["dashboard"]
        except (urllib.error.URLError, ConnectionResetError):
            if attempt == 39:
                raise
            time.sleep(1)


@pytest.mark.skipif(os.getenv("M3_QA_INTEGRATION") != "1", reason="run after docker compose up")
def test_m3_postgres_ingestion_idempotency_and_dashboard_queries():
    """Use live analytics SQL and PostgreSQL rows; opt in after Compose is healthy."""
    suffix = uuid4().hex
    pred, plan, observation = prediction(suffix), experiment(suffix), actual(suffix)
    external = prediction(suffix + "-external", source="external")
    external["app_id"] = pred["app_id"]
    external["predicted_at"] = pred["predicted_at"]
    external["churn_probability"] = 0.1
    try:
        assert _grafana_dashboard()["uid"] == "smart-retention"
        assert _api("POST", "/v1/ingest/predictions", pred)[1]["status"] == "stored"
        retry = {**pred, "predicted_at": "2030-01-01T00:00:00Z"}
        status, response = _api("POST", "/v1/ingest/predictions", retry)
        assert status == 201 and response["status"] == "duplicate"
        status, readback = _api("GET", f"/v1/predictions/{pred['prediction_id']}")
        assert status == 200
        assert readback["prediction_source"] == "mock"
        assert readback["model_version"] == pred["model_version"]
        assert datetime.fromisoformat(readback["predicted_at"]) == datetime.fromisoformat(
            pred["predicted_at"]
        )
        conflict = {**pred, "churn_probability": 0.2}
        assert _api("POST", "/v1/ingest/predictions", conflict)[0] == 409
        assert _psql(f"SELECT count(*) FROM churn_predictions WHERE prediction_id='{pred['prediction_id']}'") == "1"
        assert _api("GET", f"/v1/predictions/{pred['prediction_id']}")[1]["churn_probability"] == 0.8

        assert _api("POST", "/v1/ingest/experiments", plan)[1]["status"] == "stored"
        assert _api("POST", "/v1/ingest/experiments", plan)[1]["status"] == "duplicate"
        changed = {**plan, "request_fingerprint": "b" * 64}
        assert _api("POST", "/v1/ingest/experiments", changed)[0] == 409
        changed = {**plan, "budget_usd": 20.0}
        assert _api("POST", "/v1/ingest/experiments", changed)[0] == 409
        status, stored = _api("GET", f"/v1/experiments/{plan['experiment_id']}")
        assert status == 200
        assert stored["budget_usd"] == 10.0
        assert stored["plan_source"] == "scenario_experiment"
        assert stored["modeled_discount_uplift"] is False
        assert _psql(f"SELECT count(*) FROM retention_experiments WHERE experiment_id='{plan['experiment_id']}'") == "1"

        assert _api("POST", "/v1/ingest/actuals", observation)[1]["status"] == "stored"
        assert _api("POST", "/v1/ingest/actuals", observation)[1]["status"] == "duplicate"
        assert _psql(f"SELECT count(*) FROM actual_observations WHERE observation_id='{observation['observation_id']}'") == "1"
        assert _psql(f"SELECT metric_name FROM actual_observations WHERE observation_id='{observation['observation_id']}'") == "renewals"
        assert _psql(f"SELECT count(*) FROM actual_observations WHERE app_id='{plan['app_id']}'") == "1"

        assert _api("POST", "/v1/ingest/predictions", external)[0] == 201
        assert _psql(f"SELECT count(*) FROM churn_predictions WHERE prediction_id='{external['prediction_id']}'") == "1"
        assert _psql("SELECT has_table_privilege('grafana_ro','churn_predictions','INSERT')") == "f"
        assert _psql("SELECT has_table_privilege('grafana_ro','retention_experiments','SELECT')") == "t"
    finally:
        _psql(f"DELETE FROM actual_observations WHERE observation_id='{observation['observation_id']}';"
              f"DELETE FROM retention_experiments WHERE experiment_id='{plan['experiment_id']}';"
              f"DELETE FROM churn_predictions WHERE prediction_id IN "
              f"('{pred['prediction_id']}','{external['prediction_id']}');")
