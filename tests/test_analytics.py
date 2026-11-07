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
