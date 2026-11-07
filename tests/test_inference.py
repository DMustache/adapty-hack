from fastapi.testclient import TestClient
from services.inference.app.main import app

client = TestClient(app)
PAYLOAD = {
    "request_id": "demo-test-1", "app_id": "lumen-demo", "user_id": "demo-u01",
    "model_id": "mock-churn-v1", "renewal_horizon_days": 30,
    "context": {"platform": "ios"}, "features": {"any_model_feature": 42},
}


def test_health():
    assert client.get("/health").json()["status"] == "ok"


def test_mock_is_static_fixture_not_trained(monkeypatch):
    monkeypatch.delenv("ANALYTICS_URL", raising=False)
    res = client.post("/v1/predict", json=PAYLOAD)
    assert res.status_code == 200, res.text
    result = res.json()
    assert result["prediction_source"] == "mock"
    assert result["churn_probability"] == 0.8
    assert result["model_version"] == "0.0.0-mock"
    assert result["user_id"] == "demo-u01"
    assert client.post("/v1/predict", json=PAYLOAD).json()["prediction_id"] == result["prediction_id"]


def test_unknown_model():
    assert client.post("/v1/predict", json={**PAYLOAD, "model_id": "missing"}).status_code == 404


def test_bad_horizon():
    assert client.post("/v1/predict", json={**PAYLOAD, "renewal_horizon_days": 0}).status_code == 422


def test_features_must_be_json_object():
    assert client.post("/v1/predict", json={**PAYLOAD, "features": "bad"}).status_code == 422


def test_future_model_schema_is_adapter_controlled():
    schema = client.get("/v1/models/mock-churn-v1/schema").json()
    assert schema["type"] == "object"
    assert client.get("/v1/models/missing/schema").status_code == 404
