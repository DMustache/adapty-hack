from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from services.analytics.app import main as analytics


app = analytics.app


def test_analytics_health_without_database():
    assert TestClient(app).get("/health").json() == {"status": "ok", "service": "analytics"}


@pytest.mark.parametrize(
    ("query", "expected_params", "expected_ids"),
    [
        ("", (), ["pred-1", "pred-2"]),
        ("?app_id=lumen-demo", ("lumen-demo",), ["pred-1"]),
    ],
)
def test_churn_risk_optional_app_filter(monkeypatch, query, expected_params, expected_ids):
    timestamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = [
        ("pred-1", "lumen-demo", "demo-u01", timestamp, 0.8),
        ("pred-2", "other-demo", "demo-u02", timestamp, 0.3),
    ]

    class FakeDB:
        def __init__(self):
            self.sql = None
            self.params = None

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def cursor(self):
            return self

        def execute(self, sql, params=None):
            self.sql = " ".join(sql.split())
            self.params = params

        def fetchall(self):
            return rows[:1] if expected_params else rows

    fake_db = FakeDB()
    monkeypatch.setattr(analytics, "db_connect", lambda: fake_db)

    response = TestClient(app).get("/v1/metrics/churn-risk" + query)

    assert response.status_code == 200
    assert [point["prediction_id"] for point in response.json()["points"]] == expected_ids
    if expected_params:
        assert fake_db.params == expected_params
    else:
        assert fake_db.params in (None, ())
    assert "%s IS NULL" not in fake_db.sql
    assert "ORDER BY predicted_at ASC, user_id ASC" in fake_db.sql


def test_prediction_model_provenance_survives_ingest_and_read(monkeypatch):
    payload = {
        "prediction_id": "pred-m1", "request_id": "req-m1", "app_id": "lumen-demo",
        "user_id": "demo-u01", "model_id": "external-test", "model_version": "2026-11-07",
        "prediction_source": "external", "predicted_at": "2026-11-07T12:00:00Z",
        "renewal_horizon_days": 30, "churn_probability": 0.4,
    }

    class FakeDB:
        rowcount = 0
        values = None
        selected_columns = None
        pending_insert_result = False

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def cursor(self):
            return self

        def execute(self, sql, params):
            if "INSERT INTO churn_predictions" in sql:
                assert "RETURNING prediction_id" in sql
                columns = sql.split("churn_predictions", 1)[1].split("VALUES", 1)[0]
                names = [name.strip() for name in columns.strip(" ()\n").split(",")]
                self.values = dict(zip(names, params))
                self.rowcount = 1
                self.pending_insert_result = True
            else:
                assert params == (payload["prediction_id"],)
                assert "model_version" in sql and "prediction_source" in sql
                columns = sql.split("SELECT", 1)[1].split("FROM", 1)[0]
                self.selected_columns = [name.strip() for name in columns.split(",")]

        def fetchone(self):
            assert self.values is not None
            if self.pending_insert_result:
                self.pending_insert_result = False
                return (self.values["prediction_id"],)
            return tuple(self.values[name] for name in self.selected_columns)

    fake_db = FakeDB()
    monkeypatch.setattr(analytics, "db_connect", lambda: fake_db)
    api = TestClient(app)

    ingested = api.post("/v1/ingest/predictions", json=payload)
    assert ingested.status_code == 201
    readback = api.get("/v1/predictions/pred-m1")
    assert readback.status_code == 200
    assert readback.json()["model_version"] == payload["model_version"]
    assert readback.json()["prediction_source"] == payload["prediction_source"]
