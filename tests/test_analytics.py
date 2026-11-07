from fastapi.testclient import TestClient
from services.analytics.app.main import app


def test_analytics_health_without_database():
    assert TestClient(app).get("/health").json() == {"status": "ok", "service": "analytics"}
