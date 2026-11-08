"""Temporal CatBoost adapter: integrity, schema, determinism, batch, performance, API propagation.

Skipped when the artifact (services/inference/models/temporal_catboost) or catboost is not installed.
"""
import hashlib
import json
import shutil
import time
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("catboost")
from services.inference.app.adapters.temporal_catboost import (
    DEFAULT_DIR,
    ArtifactIntegrityError,
    TemporalCatBoostAdapter,
)

if not (DEFAULT_DIR / "model.cbm").exists():
    pytest.skip("temporal model artifact not installed", allow_module_level=True)

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "temporal_churn_fixture.json"


@pytest.fixture(scope="module")
def adapter():
    a = TemporalCatBoostAdapter()
    a.load()
    return a


@pytest.fixture(scope="module")
def fixture():
    return json.loads(FIXTURE.read_text())


def test_metadata_and_schema(adapter):
    schema = adapter.get_input_schema()
    assert schema["additionalProperties"] is False and set(schema["required"]) == set(adapter.features)
    assert adapter.source == "external" and adapter.model_id == "lumen-temporal-catboost"
    assert adapter.model_version == "1.0.0"
    expected_sha = "4f3fd0acc9944b19fd0743d3c0b8a8863b8d59e1e81065c5a0940d5b9fad1491"
    assert hashlib.sha256((DEFAULT_DIR / "model.cbm").read_bytes()).hexdigest() == expected_sha
    assert json.loads((DEFAULT_DIR / "metadata.json").read_text())["sha256"] == expected_sha
    for needed in ("days_until_renewal", "days_since_last_payment", "tenure_days", "renewal_count",
                   "historical_renewal_success_rate", "billing_issues_last_30d", "auto_renew_off"):
        assert needed in adapter.features


def test_deterministic_fixture(adapter, fixture):
    for case in fixture["cases"]:
        assert adapter.predict(case["user_id"], case["features"], {}) == pytest.approx(case["expected"], abs=1e-9)


def test_batch_matches_single(adapter, fixture):
    rows = [c["features"] for c in fixture["cases"]]
    batch = adapter.predict_batch(rows)
    assert batch == pytest.approx([adapter.predict("u", r, {}) for r in rows], abs=1e-12)


def test_missing_values_are_accepted(adapter, fixture):
    row = dict(fixture["cases"][0]["features"])
    row["historical_renewal_success_rate"] = None
    row["onboarding_goal"] = None
    assert 0 <= adapter.predict("u", row, {}) <= 1


def test_performance_budget(adapter, fixture):
    rows = [fixture["cases"][i % len(fixture["cases"])]["features"] for i in range(2000)]
    t = time.perf_counter()
    adapter.predict_batch(rows)
    assert time.perf_counter() - t < 2.0          # 2,000 snapshots in under 2 s


def test_tampered_artifact_is_refused(tmp_path):
    for f in DEFAULT_DIR.iterdir():
        shutil.copy(f, tmp_path / f.name)
    data = bytearray((tmp_path / "model.cbm").read_bytes())
    data[-1] ^= 0xFF
    (tmp_path / "model.cbm").write_bytes(bytes(data))
    with pytest.raises(ArtifactIntegrityError):
        TemporalCatBoostAdapter(tmp_path).load()


def test_predict_endpoint_propagates_temporal_fields(monkeypatch, adapter, fixture):
    from services.inference.app import main as inference
    monkeypatch.setitem(inference.ADAPTERS, adapter.model_id, adapter)
    forward = AsyncMock()
    monkeypatch.setattr(inference, "forward_to_analytics", forward)
    case = fixture["cases"][0]
    body = {"request_id": "t-1", "app_id": "lumen", "user_id": case["user_id"], "model_id": adapter.model_id,
            "renewal_horizon_days": 3, "features": case["features"], "as_of_at": case["as_of_at"],
            "renewal_due_at": case["renewal_due_at"], "renewal_price_usd": 6.99}
    res = TestClient(inference.app).post("/v1/predict", json=body)
    assert res.status_code == 200, res.text
    out = res.json()
    assert out["churn_probability"] == pytest.approx(case["expected"], abs=1e-9)
    assert out["as_of_at"].startswith(case["as_of_at"][:19]) and out["renewal_price_usd"] == 6.99
    assert out["prediction_source"] == "external"
    assert out["model_id"] == "lumen-temporal-catboost" and out["model_version"] == "1.0.0"
    stored = forward.await_args.args[1]
    assert stored["as_of_at"] and stored["renewal_due_at"] and stored["renewal_price_usd"] == 6.99


def test_invalid_features_rejected_by_schema(monkeypatch, adapter, fixture):
    from services.inference.app import main as inference
    monkeypatch.setitem(inference.ADAPTERS, adapter.model_id, adapter)
    feats = dict(fixture["cases"][0]["features"])
    feats["days_until_renewal"] = "soon"
    body = {"request_id": "t-2", "app_id": "lumen", "user_id": "u", "model_id": adapter.model_id,
            "renewal_horizon_days": 3, "features": feats}
    assert TestClient(inference.app).post("/v1/predict", json=body).status_code == 422
    missing = {k: v for k, v in fixture["cases"][0]["features"].items() if k != "tenure_days"}
    assert TestClient(inference.app).post("/v1/predict", json={**body, "features": missing}).status_code == 422
