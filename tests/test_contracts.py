import json
from pathlib import Path
from jsonschema import validate
from shared.contracts.models import (
    ActualObservation, ChurnPredictionRequest, ChurnPredictionResult,
    RetentionPlanRequest, RetentionPlanResult,
)

ROOT = Path(__file__).resolve().parents[1]


def test_json_schemas_are_fresh():
    for model, name in [
        (ChurnPredictionRequest,"churn-prediction-request"),
        (ChurnPredictionResult,"churn-prediction-result"),
        (RetentionPlanRequest,"retention-plan-request"),
        (RetentionPlanResult,"retention-plan-result"),
        (ActualObservation,"actual-observation"),
    ]:
        existing=json.loads((ROOT/"contracts"/"schemas"/f"{name}.schema.json").read_text())
        assert existing==model.model_json_schema()


def test_examples_match_schemas():
    for name in ("churn-prediction-request","churn-prediction-result","retention-plan-request"):
        schema=json.loads((ROOT/"contracts"/"schemas"/f"{name}.schema.json").read_text())
        example=json.loads((ROOT/"contracts"/"examples"/f"{name}.json").read_text())
        validate(example,schema)
