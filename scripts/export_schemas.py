#!/usr/bin/env python3
"""Lead-only: regenerate committed contracts before dispatching worker jobs."""
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from shared.contracts.models import (
    ActualObservation, ChurnPredictionRequest, ChurnPredictionResult,
    RetentionPlanRequest, RetentionPlanResult, RetentionAtRiskResponse,
)
for model, name in [
    (ChurnPredictionRequest, "churn-prediction-request"),
    (ChurnPredictionResult, "churn-prediction-result"),
    (RetentionPlanRequest, "retention-plan-request"),
    (RetentionPlanResult, "retention-plan-result"),
    (RetentionAtRiskResponse, "retention-at-risk-response"),
    (ActualObservation, "actual-observation"),
]:
    target = ROOT / "contracts" / "schemas" / f"{name}.schema.json"
    target.write_text(json.dumps(model.model_json_schema(), indent=2, ensure_ascii=False) + "\n")
    print(target.relative_to(ROOT))
