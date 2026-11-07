"""Persistence and aggregation. Does not model churn or treatment uplift."""
import json
import os
from fastapi import FastAPI, HTTPException
from shared.contracts.models import ActualObservation, ChurnPredictionResult, RetentionPlanResult

app = FastAPI(title="Smart Retention Offers — Analytics Infrastructure", version="0.2.0")


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
               prediction_source, predicted_at, renewal_horizon_days, churn_probability)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (prediction_id) DO NOTHING
        """, (
            prediction.prediction_id, prediction.request_id, prediction.app_id,
            prediction.user_id, prediction.model_id, prediction.model_version,
            prediction.prediction_source, prediction.predicted_at,
            prediction.renewal_horizon_days, prediction.churn_probability,
        ))
        inserted = cur.rowcount == 1
    return {"status": "stored" if inserted else "duplicate", "prediction_id": prediction.prediction_id}


@app.post("/v1/ingest/experiments", status_code=201)
def ingest_experiment(plan: RetentionPlanResult):
    # Immutable experiment snapshots. Duplicate ID + different payload is rejected rather than overwritten.
    payload = json.dumps(plan.model_dump(mode="json"), sort_keys=True)
    with db_connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT payload FROM retention_experiments WHERE experiment_id = %s", (plan.experiment_id,))
        existing = cur.fetchone()
        if existing:
            if existing[0].get("request_fingerprint") != plan.request_fingerprint:
                raise HTTPException(status_code=409, detail="experiment_id already exists for another request")
            return {"status": "duplicate", "experiment_id": plan.experiment_id}
        cur.execute("""
            INSERT INTO retention_experiments
              (experiment_id, app_id, created_at, budget_usd, max_exposure_usd, payload)
            VALUES (%s,%s,%s,%s,%s,%s::jsonb)
        """, (plan.experiment_id, plan.app_id, plan.created_at, plan.budget_usd,
              plan.max_allocated_discount_exposure_usd, payload))
    return {"status": "stored", "experiment_id": plan.experiment_id}


@app.get("/v1/experiments/{experiment_id}")
def get_experiment(experiment_id: str):
    with db_connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT payload FROM retention_experiments WHERE experiment_id=%s", (experiment_id,))
        result = cur.fetchone()
    if result is None:
        raise HTTPException(status_code=404, detail="Experiment not found")
    return result[0]


@app.post("/v1/ingest/actuals", status_code=201)
def ingest_actual(observation: ActualObservation):
    with db_connect() as conn, conn.cursor() as cur:
        cur.execute("""
            INSERT INTO actual_observations
              (observation_id, app_id, metric_name, metric_value, observed_at, dimensions, source)
            VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s)
            ON CONFLICT (observation_id) DO NOTHING
        """, (observation.observation_id, observation.app_id, observation.metric_name,
              observation.metric_value, observation.observed_at,
              json.dumps(observation.dimensions), observation.source))
        inserted = cur.rowcount == 1
    return {"status": "stored" if inserted else "duplicate", "observation_id": observation.observation_id}


@app.get("/v1/predictions/{prediction_id}")
def get_prediction(prediction_id: str):
    with db_connect() as conn, conn.cursor() as cur:
        cur.execute("""
          SELECT prediction_id, app_id, user_id, model_id, model_version, prediction_source,
                 churn_probability, predicted_at, renewal_horizon_days
          FROM churn_predictions WHERE prediction_id=%s
        """, (prediction_id,))
        row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Prediction not found")
    return dict(zip(("prediction_id", "app_id", "user_id", "model_id", "model_version",
                     "prediction_source",
                     "churn_probability", "predicted_at", "renewal_horizon_days"), row))


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
