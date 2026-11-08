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


def _register_temporal_model() -> None:
    """Load the approved artifact; a broken installation must fail startup."""
    from services.inference.app.adapters.temporal_catboost import DEFAULT_DIR, TemporalCatBoostAdapter
    if not DEFAULT_DIR.exists() and not os.getenv("TEMPORAL_CHURN_MODEL_DIR"):
        logger.info("Temporal churn artifact directory not installed")
        return
    adapter = TemporalCatBoostAdapter()
    ADAPTERS[adapter.model_id] = adapter


_register_temporal_model()
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
    as_of_at, renewal_due_at, renewal_price_usd = (
        request.as_of_at, request.renewal_due_at, request.renewal_price_usd
    )
    if request.model_id == "lumen-temporal-catboost":
        context = request.context
        if set(context) - {"as_of_at", "renewal_due_at", "feature_source_ref"}:
            raise HTTPException(status_code=422, detail="Unknown temporal context field")
        try:
            if "as_of_at" in context:
                as_of_at = datetime.fromisoformat(context["as_of_at"].replace("Z", "+00:00"))
            if "renewal_due_at" in context:
                renewal_due_at = datetime.fromisoformat(context["renewal_due_at"].replace("Z", "+00:00"))
        except (AttributeError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail="Invalid temporal context time") from exc
        renewal_price_usd = request.features["renewal_price_usd"]
        if request.renewal_price_usd is not None and request.renewal_price_usd != renewal_price_usd:
            raise HTTPException(status_code=422, detail="Conflicting renewal prices")
        if as_of_at is None or renewal_due_at is None or as_of_at.tzinfo is None or renewal_due_at.tzinfo is None:
            raise HTTPException(status_code=422, detail="Temporal model requires UTC cutoff and renewal times")
        if as_of_at.utcoffset().total_seconds() != 0 or renewal_due_at.utcoffset().total_seconds() != 0:
            raise HTTPException(status_code=422, detail="Temporal times must be UTC")
        if renewal_due_at <= as_of_at:
            raise HTTPException(status_code=422, detail="Renewal must follow feature cutoff")
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
        as_of_at=as_of_at, renewal_due_at=renewal_due_at,
        renewal_price_usd=renewal_price_usd,
    )
    await forward_to_analytics("/v1/ingest/predictions", result.model_dump(mode="json"))
    return result


@app.post("/v1/retention/plan", response_model=RetentionPlanResult)
async def retention_plan(request: RetentionPlanRequest):
    result = make_plan(request)
    await forward_to_analytics("/v1/ingest/experiments", result.model_dump(mode="json"))
    return result
