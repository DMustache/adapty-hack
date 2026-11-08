"""Temporal prediction records: contract compatibility, analytics persistence/trajectory, SQL views, Grafana."""
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from services.analytics.app import main as analytics
from shared.contracts.models import ChurnPredictionRequest, ChurnPredictionResult

ROOT = Path(__file__).resolve().parents[1]
BASE_RESULT = {
    "prediction_id": "pred-t1", "request_id": "req-t1", "app_id": "lumen", "user_id": "u00027",
    "model_id": "lumen-temporal-catboost", "model_version": "1.0.0", "prediction_source": "external",
    "predicted_at": "2026-11-08T10:00:00Z", "renewal_horizon_days": 3, "churn_probability": 0.12,
}


# ---------------------------------------------------------------- contracts
def test_old_payloads_without_temporal_fields_still_validate():
    for name in ("churn-prediction-request", "churn-prediction-result"):
        example = json.loads((ROOT / "contracts" / "examples" / f"{name}.json").read_text())
        model = ChurnPredictionRequest if "request" in name else ChurnPredictionResult
        parsed = model.model_validate(example)
        assert parsed.as_of_at is None and parsed.renewal_due_at is None and parsed.renewal_price_usd is None


def test_temporal_fields_round_trip():
    r = ChurnPredictionResult.model_validate({**BASE_RESULT, "as_of_at": "2026-10-20T08:00:00Z",
                                              "renewal_due_at": "2026-10-23T08:00:00Z", "renewal_price_usd": 6.99})
    assert r.as_of_at.tzinfo is not None and r.renewal_price_usd == 6.99


@pytest.mark.parametrize("extra", [
    {"as_of_at": "2026-10-23T08:00:00Z", "renewal_due_at": "2026-10-20T08:00:00Z"},   # due before as-of
    {"as_of_at": "2026-10-20T08:00:00"},                                               # no timezone
    {"renewal_price_usd": 0},
    {"renewal_price_usd": -1},
])
def test_invalid_temporal_fields_rejected(extra):
    with pytest.raises(ValidationError):
        ChurnPredictionResult.model_validate({**BASE_RESULT, **extra})


# ---------------------------------------------------------------- analytics
class FakeDB:
    def __init__(self, rows=None):
        self.rows, self.sql, self.params, self.values, self.rowcount = rows or [], None, None, None, 0

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def cursor(self):
        return self

    def execute(self, sql, params=None):
        self.sql, self.params = " ".join(sql.split()), params
        if "INSERT INTO churn_predictions" in sql:
            cols = sql.split("churn_predictions", 1)[1].split("VALUES", 1)[0]
            self.values = dict(zip([c.strip() for c in cols.strip(" ()\n").split(",")], params))
            self.rowcount = 1

    def fetchall(self):
        return self.rows


def test_ingest_stores_temporal_columns(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(analytics, "db_connect", lambda: db)
    payload = {**BASE_RESULT, "as_of_at": "2026-10-20T08:00:00Z", "renewal_due_at": "2026-10-23T08:00:00Z",
               "renewal_price_usd": 6.99}
    assert TestClient(analytics.app).post("/v1/ingest/predictions", json=payload).status_code == 201
    assert db.values["as_of_at"] == datetime(2026, 10, 20, 8, tzinfo=timezone.utc)
    assert db.values["renewal_due_at"] == datetime(2026, 10, 23, 8, tzinfo=timezone.utc)
    assert db.values["renewal_price_usd"] == 6.99


def test_ingest_without_temporal_fields_stores_nulls(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(analytics, "db_connect", lambda: db)
    assert TestClient(analytics.app).post("/v1/ingest/predictions", json=BASE_RESULT).status_code == 201
    assert db.values["as_of_at"] is None and db.values["renewal_price_usd"] is None


def test_trajectory_endpoint(monkeypatch):
    t1 = datetime(2026, 10, 20, tzinfo=timezone.utc)
    t2 = datetime(2026, 10, 21, tzinfo=timezone.utc)
    due = datetime(2026, 10, 23, tzinfo=timezone.utc)
    db = FakeDB(rows=[("p1", "lumen", "m", t1, due, 0.10, None, None, 0.699),
                      ("p2", "lumen", "m", t2, due, 0.25, 0.10, 0.15, 1.7475)])
    monkeypatch.setattr(analytics, "db_connect", lambda: db)
    res = TestClient(analytics.app).get("/v1/metrics/churn-trajectory?user_id=u1&app_id=lumen")
    assert res.status_code == 200
    pts = res.json()["points"]
    assert [p["churn_probability"] for p in pts] == [0.10, 0.25]
    assert pts[0]["churn_probability_change"] is None and pts[1]["churn_probability_change"] == pytest.approx(0.15)
    assert pts[1]["expected_revenue_at_risk_usd"] == pytest.approx(1.7475)
    assert db.params == ("u1", "lumen") and "FROM churn_risk_trajectory" in db.sql
    assert "ORDER BY model_id ASC, effective_at ASC" in db.sql


def test_trajectory_requires_user_id():
    assert TestClient(analytics.app).get("/v1/metrics/churn-trajectory").status_code == 422


# ---------------------------------------------------------------- SQL and Grafana
def test_migration_adds_columns_views_and_grafana_grant():
    sql = (ROOT / "postgres" / "init" / "003-temporal-predictions.sql").read_text()
    for col in ("as_of_at", "renewal_due_at", "renewal_price_usd"):
        assert f"ADD COLUMN IF NOT EXISTS {col}" in sql
    assert "CREATE OR REPLACE VIEW churn_risk_trajectory" in sql and "CREATE OR REPLACE VIEW churn_risk_current" in sql
    assert "LAG(p.churn_probability)" in sql and "churn_probability * p.renewal_price_usd" in sql
    assert "GRANT SELECT ON churn_risk_trajectory, churn_risk_current TO grafana_ro" in sql


def test_grafana_dashboard_panels():
    d = json.loads((ROOT / "grafana" / "dashboards" / "churn-risk-trajectory.json").read_text())
    titles = " | ".join(p["title"] for p in d["panels"])
    for needed in ("Current churn probability", "trajectory", "Change in churn risk since the previous prediction",
                   "revenue at risk"):
        assert needed.lower() in titles.lower(), needed
    for p in d["panels"]:
        assert p["datasource"]["uid"] == "adapty-pg"
        sql = p["targets"][0]["rawSql"]
        assert "churn_risk_" in sql and "'$model'" in sql
    assert {v["name"] for v in d["templating"]["list"]} == {"model", "user"}
    ids = [p["id"] for p in d["panels"]]
    assert len(ids) == len(set(ids))
