"""External churn model adapter + *non-ML* retention experiment economics."""
import logging
import math
import os
import uuid
from datetime import datetime, timezone
import httpx
from fastapi import FastAPI, HTTPException
from jsonschema import ValidationError, validate
from shared.contracts.models import (
    ChurnPredictionRequest, ChurnPredictionResult, RetentionPlanRequest, RetentionPlanResult,
)
from services.inference.app.adapters.mock import MockChurnAdapter
from services.inference.app.economics import make_plan

logger = logging.getLogger("retention")
app = FastAPI(title="Smart Retention Offers — Inference & Planning", version="0.2.0")
ADAPTERS = {MockChurnAdapter.model_id: MockChurnAdapter()}
for adapter in ADAPTERS.values():
    adapter.load()


async def forward_to_analytics(path: str, payload: dict):
    base = os.getenv("ANALYTICS_URL", "")
    if not base:
        return
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(base.rstrip("/") + path, json=payload)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.exception("Analytics delivery failed: %s", path)
        raise HTTPException(status_code=502, detail="Analytics persistence failed") from exc


@app.get("/health")
def health():
    return {"status": "ok", "service": "retention-inference"}


@app.get("/v1/models")
def list_models():
    return [{"model_id": a.model_id, "model_version": a.model_version, "source": a.source}
            for a in ADAPTERS.values()]


@app.get("/v1/models/{model_id}/schema")
def model_schema(model_id: str):
    adapter = ADAPTERS.get(model_id)
    if adapter is None:
        raise HTTPException(status_code=404, detail="Unknown model_id")
    return adapter.get_input_schema()


@app.post("/v1/predict", response_model=ChurnPredictionResult)
async def predict(request: ChurnPredictionRequest):
    adapter = ADAPTERS.get(request.model_id)
    if adapter is None:
        raise HTTPException(status_code=404, detail="Unknown model_id")
    try:
        validate(instance=request.features, schema=adapter.get_input_schema())
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid model features: {exc.message}") from exc
    probability = adapter.predict(request.user_id, request.features, request.context)
    if (isinstance(probability, bool) or not isinstance(probability, (int, float))
            or not math.isfinite(probability) or not 0 <= probability <= 1):
        logger.error("Adapter %s returned an invalid churn probability", adapter.model_id)
        raise HTTPException(status_code=502, detail="Invalid model prediction")
    prediction_id = str(uuid.uuid5(uuid.NAMESPACE_URL,
        f"{request.app_id}/{request.model_id}/{request.request_id}/{request.user_id}"))
    result = ChurnPredictionResult(
        prediction_id=prediction_id, request_id=request.request_id,
        app_id=request.app_id, user_id=request.user_id,
        model_id=adapter.model_id, model_version=adapter.model_version,
        prediction_source=adapter.source, predicted_at=datetime.now(timezone.utc),
        renewal_horizon_days=request.renewal_horizon_days,
        churn_probability=float(probability),
    )
    await forward_to_analytics("/v1/ingest/predictions", result.model_dump(mode="json"))
    return result


@app.post("/v1/retention/plan", response_model=RetentionPlanResult)
async def retention_plan(request: RetentionPlanRequest):
    result = make_plan(request)
    await forward_to_analytics("/v1/ingest/experiments", result.model_dump(mode="json"))
    return result
