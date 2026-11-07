from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from services.inference.app import main as inference

app = inference.app

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


@pytest.mark.parametrize("invalid_probability", [float("nan"), float("inf"), -0.01, 1.01, "bad"])
def test_invalid_adapter_output_fails_before_persistence(monkeypatch, invalid_probability):
    class ExternalAdapter:
        model_id = "external-test"
        model_version = "v1"
        source = "external"

        def get_input_schema(self):
            return {"type": "object"}

        def predict(self, user_id, features, context):
            return invalid_probability

    forward = AsyncMock()
    monkeypatch.setitem(inference.ADAPTERS, "external-test", ExternalAdapter())
    monkeypatch.setattr(inference, "forward_to_analytics", forward)

    response = TestClient(app, raise_server_exceptions=False).post(
        "/v1/predict", json={**PAYLOAD, "model_id": "external-test"}
    )

    assert response.status_code == 502
    assert response.json()["detail"] == "Invalid model prediction"
    forward.assert_not_awaited()


def test_adapter_specific_feature_schema_rejects_invalid_input(monkeypatch):
    class SchemaAdapter:
        model_id = "schema-test"
        model_version = "v1"
        source = "external"

        def get_input_schema(self):
            return {
                "type": "object",
                "properties": {"sessions": {"type": "integer"}},
                "required": ["sessions"],
                "additionalProperties": False,
            }

        def predict(self, user_id, features, context):
            return 0.4

    monkeypatch.setitem(inference.ADAPTERS, "schema-test", SchemaAdapter())
    response = client.post("/v1/predict", json={**PAYLOAD, "model_id": "schema-test", "features": {"sessions": "two"}})
    assert response.status_code == 422
