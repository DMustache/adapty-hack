"""Frozen M5 model interface and fixture checks independent of adapter implementation."""

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "services/inference/models/temporal_catboost"
SHA = "4f3fd0acc9944b19fd0743d3c0b8a8863b8d59e1e81065c5a0940d5b9fad1491"


def read(path):
    return json.loads((ROOT / path).read_text())


def test_pinned_metadata_matches_fixture_and_artifact():
    metadata = read("contracts/examples/model-metadata.json")
    schema = read("contracts/schemas/model-metadata.schema.json")
    fixture = read("tests/fixtures/temporal_churn_fixture.json")
    Draft202012Validator(schema).validate(metadata)
    assert (metadata["model_id"], metadata["model_version"], metadata["artifact_sha256"]) == (
        fixture["model_id"], fixture["model_version"], fixture["sha256"]
    ) == ("lumen-temporal-catboost", "1.0.0", SHA)
    assert hashlib.sha256((MODEL / "model.cbm").read_bytes()).hexdigest() == SHA
    assert len(metadata["features"]) == 23
    assert list(fixture["cases"][0]["features"]) == metadata["features"]


def test_temporal_request_schema_accepts_fixture_and_rejects_bad_features():
    request = read("contracts/examples/temporal-churn-request.json")
    schema = read("contracts/schemas/temporal-churn-request.schema.json")
    validator = Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER)
    validator.validate(request)
    assert request["user_id"].startswith("synthetic-")
    mutations = [
        lambda r: r["features"].pop("tenure_days"),
        lambda r: r["features"].update(days_until_renewal="tomorrow"),
        lambda r: r["features"].update(unknown_feature=1),
        lambda r: r["context"].update(as_of_at="2026-07-08T09:34:54"),
        lambda r: r.update(model_id="mock-churn-v1"),
    ]
    for mutate in mutations:
        bad = deepcopy(request)
        mutate(bad)
        assert not validator.is_valid(bad)


@pytest.mark.parametrize("field", ["model_id", "model_version", "artifact_sha256"])
def test_metadata_pin_rejects_changed_identity(field):
    metadata = read("contracts/examples/model-metadata.json")
    schema = read("contracts/schemas/model-metadata.schema.json")
    metadata[field] = "changed"
    assert not Draft202012Validator(schema).is_valid(metadata)
