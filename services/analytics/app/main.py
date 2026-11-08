"""Persistence and aggregation. Does not model churn or treatment uplift."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from jsonschema import Draft202012Validator

from shared.contracts.models import (
    ActualObservation, ChurnPredictionResult, RetentionAtRiskResponse, RetentionPlanResult,
)

app = FastAPI(title="Smart Retention Offers — Analytics Infrastructure", version="0.2.0")
LINEAGE_KINDS = ("actual-assignment", "actual-exposure", "next-renewal-outcome")
SCHEMA_DIR = Path(__file__).resolve().parents[3] / "contracts" / "schemas"


def _lineage_validator(kind: str) -> Draft202012Validator:
    if kind not in LINEAGE_KINDS:
        raise HTTPException(status_code=404, detail="Unknown lineage event kind")
    return Draft202012Validator(json.loads((SCHEMA_DIR / f"{kind}.schema.json").read_text()),
                                format_checker=Draft202012Validator.FORMAT_CHECKER)


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0:
        raise HTTPException(status_code=422, detail="Lineage event timestamps must be UTC")
    return parsed.astimezone(timezone.utc)


def db_connect():
    import psycopg
    return psycopg.connect(os.environ["DATABASE_URL"])


@app.get("/health")
def health():
    return {"status": "ok", "service": "analytics"}


@app.post("/v1/ingest/predictions", status_code=201)
def ingest_prediction(prediction: ChurnPredictionResult):
    with db_connect() as conn, conn.cursor() as cur:
        cur.execute("""
            INSERT INTO churn_predictions
              (prediction_id, request_id, app_id, user_id, model_id, model_version,
               prediction_source, predicted_at, renewal_horizon_days, churn_probability,
               as_of_at, renewal_due_at, renewal_price_usd, plan_type)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (prediction_id) DO NOTHING
            RETURNING prediction_id
        """, (
            prediction.prediction_id, prediction.request_id, prediction.app_id,
            prediction.user_id, prediction.model_id, prediction.model_version,
            prediction.prediction_source, prediction.predicted_at,
            prediction.renewal_horizon_days, prediction.churn_probability,
            prediction.as_of_at, prediction.renewal_due_at, prediction.renewal_price_usd,
            prediction.plan_type,
        ))
        inserted = cur.fetchone() is not None
        if not inserted:
            # A separate statement sees a concurrent insert after ON CONFLICT has waited for it.
            cur.execute("""
                SELECT request_id, app_id, user_id, model_id, model_version,
                       prediction_source, renewal_horizon_days, churn_probability,
                       as_of_at, renewal_due_at, renewal_price_usd, plan_type
                FROM churn_predictions WHERE prediction_id = %s
            """, (prediction.prediction_id,))
            stored = cur.fetchone()
            stable_fields = (
                prediction.request_id, prediction.app_id, prediction.user_id,
                prediction.model_id, prediction.model_version, prediction.prediction_source,
                prediction.renewal_horizon_days, prediction.churn_probability,
            )
            if stored is None or stored[:8] != stable_fields or stored[8:10] != (
                prediction.as_of_at, prediction.renewal_due_at
            ) or (float(stored[10]) if stored[10] is not None else None) != prediction.renewal_price_usd \
                    or stored[11] != prediction.plan_type:
                raise HTTPException(status_code=409, detail="prediction_id already exists with different content")
    return {"status": "stored" if inserted else "duplicate", "prediction_id": prediction.prediction_id}


@app.post("/v1/ingest/experiments", status_code=201)
def ingest_experiment(plan: RetentionPlanResult):
    # Immutable experiment snapshots. Duplicate ID + different payload is rejected rather than overwritten.
    result = plan.model_dump(mode="json")
    payload = json.dumps(result, sort_keys=True)
    with db_connect() as conn, conn.cursor() as cur:
        cur.execute("""
            INSERT INTO retention_experiments
              (experiment_id, app_id, created_at, budget_usd, max_exposure_usd, payload)
            VALUES (%s,%s,%s,%s,%s,%s::jsonb)
            ON CONFLICT (experiment_id) DO NOTHING
            RETURNING experiment_id
        """, (plan.experiment_id, plan.app_id, plan.created_at, plan.budget_usd,
              plan.max_allocated_discount_exposure_usd, payload))
        inserted = cur.fetchone() is not None
        if not inserted:
            cur.execute("SELECT payload FROM retention_experiments WHERE experiment_id = %s", (plan.experiment_id,))
            stored = cur.fetchone()[0]
            if stored.get("request_fingerprint") != plan.request_fingerprint:
                raise HTTPException(status_code=409, detail="experiment_id already exists for another request")
            if stored != result:
                raise HTTPException(status_code=409, detail="experiment_id already exists with different content")
    return {"status": "stored" if inserted else "duplicate", "experiment_id": plan.experiment_id}


@app.get("/v1/experiments/{experiment_id}")
def get_experiment(experiment_id: str):
    with db_connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT payload FROM retention_experiments WHERE experiment_id=%s", (experiment_id,))
        result = cur.fetchone()
    if result is None:
        raise HTTPException(status_code=404, detail="Experiment not found")
    return result[0]


@app.post("/v1/ingest/lineage/{kind}", status_code=201)
def ingest_lineage(kind: str, event: dict):
    errors = list(_lineage_validator(kind).iter_errors(event))
    if errors:
        raise HTTPException(status_code=422, detail=errors[0].message)
    event_at, ingested_at = _utc(event["event_at"]), _utc(event["ingested_at"])
    as_of_at, due_at = _utc(event["as_of_at"]), _utc(event["renewal_due_at"])
    if not as_of_at < due_at or event_at < as_of_at:
        raise HTTPException(status_code=422, detail="Invalid feature cutoff or event order")
    if kind == "next-renewal-outcome" and (
        event_at < _utc(event["outcome_mature_at"]) or _utc(event["outcome_mature_at"]) < due_at
    ):
        raise HTTPException(status_code=422, detail="Outcome is not mature")
    with db_connect() as conn, conn.cursor() as cur:
        cur.execute("""SELECT app_id, user_id, model_id, model_version, as_of_at, renewal_due_at
                       FROM churn_predictions WHERE prediction_id=%s""", (event["prediction_id"],))
        prediction = cur.fetchone()
        if prediction is None or prediction != (
            event["app_id"], event["user_id"], event["model_id"], event["model_version"], as_of_at, due_at
        ):
            raise HTTPException(status_code=422, detail="Prediction lineage does not match")
        if kind != "actual-assignment":
            cur.execute("""SELECT variation_id, user_id, prediction_id FROM experiment_lineage
                           WHERE kind='actual-assignment' AND app_id=%s AND experiment_id=%s
                             AND assignment_id=%s""", (event["app_id"], event["experiment_id"], event["assignment_id"]))
            if cur.fetchone() != (event["variation_id"], event["user_id"], event["prediction_id"]):
                raise HTTPException(status_code=422, detail="Assignment lineage does not match")
        if kind == "next-renewal-outcome":
            cur.execute("""SELECT variation_id, user_id, prediction_id FROM experiment_lineage
                           WHERE kind='actual-exposure' AND app_id=%s AND experiment_id=%s
                             AND assignment_id=%s AND exposure_id=%s""", (
                event["app_id"], event["experiment_id"], event["assignment_id"], event["exposure_id"]))
            if cur.fetchone() != (event["variation_id"], event["user_id"], event["prediction_id"]):
                raise HTTPException(status_code=422, detail="Exposure lineage does not match")
        cur.execute("""INSERT INTO experiment_lineage
                       (kind, app_id, idempotency_key, source, source_event_id, prediction_id,
                        user_id, model_id, model_version, experiment_id, variation_id,
                        assignment_id, exposure_id, event_at, ingested_at, payload)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                       ON CONFLICT DO NOTHING
                       RETURNING idempotency_key""", (
            kind, event["app_id"], event["idempotency_key"], event["source"],
            event["source_event_id"], event["prediction_id"], event["user_id"],
            event["model_id"], event["model_version"], event["experiment_id"],
            event["variation_id"], event["assignment_id"], event.get("exposure_id"),
            event_at, ingested_at, json.dumps(event, sort_keys=True)))
        inserted = cur.fetchone() is not None
        if not inserted:
            cur.execute("""SELECT payload FROM experiment_lineage
                           WHERE kind=%s AND app_id=%s AND idempotency_key=%s""", (
                kind, event["app_id"], event["idempotency_key"]))
            stored = cur.fetchone()
            if stored is None or stored[0] != event:
                raise HTTPException(status_code=409, detail="Idempotency key already has different content")
    return {"status": "stored" if inserted else "duplicate", "kind": kind,
            "idempotency_key": event["idempotency_key"]}


@app.get("/v1/lineage/{experiment_id}")
def get_lineage(experiment_id: str, app_id: str):
    with db_connect() as conn, conn.cursor() as cur:
        cur.execute("""SELECT kind, payload FROM experiment_lineage
                       WHERE app_id=%s AND experiment_id=%s
                       ORDER BY event_at, kind, idempotency_key""", (app_id, experiment_id))
        rows = cur.fetchall()
    return {"app_id": app_id, "experiment_id": experiment_id,
            "events": [{"kind": kind, **payload} for kind, payload in rows]}


@app.post("/v1/ingest/actuals", status_code=201)
def ingest_actual(observation: ActualObservation):
    with db_connect() as conn, conn.cursor() as cur:
        cur.execute("""
            INSERT INTO actual_observations
              (observation_id, app_id, metric_name, metric_value, observed_at, dimensions, source)
            VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s)
            ON CONFLICT (observation_id) DO NOTHING
            RETURNING observation_id
        """, (observation.observation_id, observation.app_id, observation.metric_name,
              observation.metric_value, observation.observed_at,
              json.dumps(observation.dimensions), observation.source))
        inserted = cur.fetchone() is not None
        if not inserted:
            cur.execute("""
                SELECT app_id, metric_name, metric_value, observed_at, dimensions, source
                FROM actual_observations WHERE observation_id = %s
            """, (observation.observation_id,))
            stored = cur.fetchone()
            expected = (
                observation.app_id, observation.metric_name, observation.metric_value,
                observation.observed_at, observation.dimensions, observation.source,
            )
            if stored != expected:
                raise HTTPException(status_code=409, detail="observation_id already exists with different content")
    return {"status": "stored" if inserted else "duplicate", "observation_id": observation.observation_id}


@app.get("/v1/predictions/{prediction_id}")
def get_prediction(prediction_id: str):
    with db_connect() as conn, conn.cursor() as cur:
        cur.execute("""
          SELECT prediction_id, request_id, app_id, user_id, model_id, model_version, prediction_source,
                 churn_probability, predicted_at, renewal_horizon_days,
                 as_of_at, renewal_due_at, renewal_price_usd, plan_type
          FROM churn_predictions WHERE prediction_id=%s
        """, (prediction_id,))
        row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Prediction not found")
    out = dict(zip(("prediction_id", "request_id", "app_id", "user_id", "model_id", "model_version",
                    "prediction_source",
                    "churn_probability", "predicted_at", "renewal_horizon_days",
                    "as_of_at", "renewal_due_at", "renewal_price_usd", "plan_type"), row))
    if out.get("renewal_price_usd") is not None:
        out["renewal_price_usd"] = float(out["renewal_price_usd"])
    return out


@app.get("/v1/metrics/churn-risk")
def churn_risk(app_id: str | None = None):
    with db_connect() as conn, conn.cursor() as cur:
        query = """
          SELECT prediction_id, app_id, user_id, predicted_at, churn_probability
          FROM churn_predictions
        """
        ordering = " ORDER BY predicted_at ASC, user_id ASC"
        if app_id is None:
            cur.execute(query + ordering)
        else:
            cur.execute(query + " WHERE app_id=%s" + ordering, (app_id,))
        rows = cur.fetchall()
    return {"points": [
        {"prediction_id": pid, "app_id": app, "user_id": uid,
         "time": ts.isoformat(), "churn_probability": float(p)}
        for pid, app, uid, ts, p in rows
    ]}


@app.get("/v1/metrics/churn-trajectory")
def churn_trajectory(user_id: str, app_id: str | None = None, model_id: str | None = None):
    """One subscriber's stored predictions in as-of order, with the change since the previous prediction and the
    expected next-renewal revenue at risk (probability x renewal price). Reads the churn_risk_trajectory view."""
    conditions, params = ["user_id=%s"], [user_id]
    if app_id is not None:
        conditions.append("app_id=%s")
        params.append(app_id)
    if model_id is not None:
        conditions.append("model_id=%s")
        params.append(model_id)
    with db_connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT prediction_id, app_id, model_id, effective_at, renewal_due_at, churn_probability, "
            "previous_churn_probability, churn_probability_change, expected_revenue_at_risk_usd "
            "FROM churn_risk_trajectory WHERE " + " AND ".join(conditions)
            + " ORDER BY model_id ASC, effective_at ASC, predicted_at ASC, prediction_id ASC",
            tuple(params))
        rows = cur.fetchall()

    def num(v):
        return None if v is None else float(v)

    return {"user_id": user_id, "points": [
        {"prediction_id": pid, "app_id": app, "model_id": mid, "as_of_at": ts.isoformat(),
         "renewal_due_at": None if due is None else due.isoformat(), "churn_probability": float(p),
         "previous_churn_probability": num(prev), "churn_probability_change": num(delta),
         "expected_revenue_at_risk_usd": num(risk)}
        for pid, app, mid, ts, due, p, prev, delta, risk in rows
    ]}


@app.get("/v1/retention/at-risk", response_model=RetentionAtRiskResponse)
def retention_at_risk(
    app_id: str = Query(min_length=1),
    model_id: str = "lumen-temporal-catboost",
    model_version: str = "1.0.0",
    as_of: datetime | None = None,
    max_age_days: float = Query(default=7, gt=0, le=365),
    limit: int = Query(default=1000, ge=1, le=100_000),
):
    """Read-only planner candidates from stored, cutoff-safe predictions."""
    if as_of is not None and (as_of.tzinfo is None or as_of.utcoffset().total_seconds() != 0):
        raise HTTPException(status_code=422, detail="as_of must be UTC")
    params = {"app_id": app_id, "model_id": model_id, "model_version": model_version, "as_of": as_of}
    with db_connect() as conn, conn.cursor() as cur:
        cur.execute("""
            WITH valid AS (
              SELECT prediction_id, app_id, user_id, model_id, model_version, prediction_source,
                     plan_type, predicted_at, as_of_at, renewal_due_at, churn_probability,
                     renewal_price_usd::double precision AS renewal_price_usd
              FROM churn_predictions
              WHERE app_id = %(app_id)s AND model_id = %(model_id)s
                AND model_version = %(model_version)s
                AND as_of_at IS NOT NULL AND renewal_due_at IS NOT NULL
                AND renewal_price_usd IS NOT NULL
            ),
            ref AS (SELECT COALESCE(%(as_of)s::timestamptz, MAX(predicted_at)) AS t FROM valid)
            SELECT DISTINCT ON (v.user_id) v.prediction_id, v.app_id, v.user_id, v.model_id,
                   v.model_version, v.prediction_source, v.plan_type, v.predicted_at, v.as_of_at,
                   v.renewal_due_at, v.churn_probability, v.renewal_price_usd, ref.t
            FROM valid v CROSS JOIN ref
            WHERE v.as_of_at <= ref.t AND v.predicted_at <= ref.t
            ORDER BY v.user_id, v.as_of_at DESC, v.predicted_at DESC, v.prediction_id DESC
        """, params)
        rows = cur.fetchall()

    reference = as_of if as_of is not None else (rows[0][-1] if rows else None)
    if reference is not None:
        reference = reference.astimezone(timezone.utc)
    counts = {"subscribers_with_predictions": len(rows), "renewal_already_due": 0,
              "stale": 0, "missing_plan_type": 0}
    kept = []
    for pid, app_, uid, mid, version, source, plan, predicted, cutoff, due, p, price, _ in rows:
        predicted, cutoff, due = (ts.astimezone(timezone.utc) for ts in (predicted, cutoff, due))
        if due <= reference:
            counts["renewal_already_due"] += 1
            continue
        if (reference - cutoff).total_seconds() > max_age_days * 86400:
            counts["stale"] += 1
            continue
        if plan is None:
            counts["missing_plan_type"] += 1
            continue
        kept.append({"prediction_id": pid, "app_id": app_, "user_id": uid,
                     "model_id": mid, "model_version": version, "prediction_source": source,
                     "plan_type": plan, "predicted_at": predicted.isoformat(),
                     "as_of_at": cutoff.isoformat(), "renewal_due_at": due.isoformat(),
                     "churn_probability": float(p), "renewal_price_usd": float(price)})
    kept.sort(key=lambda row: (-row["churn_probability"] * row["renewal_price_usd"], row["user_id"]))
    counts["eligible"] = len(kept)
    counts["returned"] = min(len(kept), limit)
    return {"model_id": model_id, "model_version": model_version, "app_id": app_id,
            "reference_time": reference.isoformat() if reference else None,
            "max_age_days": max_age_days, "counts": counts, "subscribers": kept[:limit]}
