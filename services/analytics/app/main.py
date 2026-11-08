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
               prediction_source, predicted_at, renewal_horizon_days, churn_probability,
               as_of_at, renewal_due_at, renewal_price_usd)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (prediction_id) DO NOTHING
            RETURNING prediction_id
        """, (
            prediction.prediction_id, prediction.request_id, prediction.app_id,
            prediction.user_id, prediction.model_id, prediction.model_version,
            prediction.prediction_source, prediction.predicted_at,
            prediction.renewal_horizon_days, prediction.churn_probability,
            prediction.as_of_at, prediction.renewal_due_at, prediction.renewal_price_usd,
        ))
        inserted = cur.fetchone() is not None
        if not inserted:
            # A separate statement sees a concurrent insert after ON CONFLICT has waited for it.
            cur.execute("""
                SELECT request_id, app_id, user_id, model_id, model_version,
                       prediction_source, renewal_horizon_days, churn_probability
                FROM churn_predictions WHERE prediction_id = %s
            """, (prediction.prediction_id,))
            stored = cur.fetchone()
            stable_fields = (
                prediction.request_id, prediction.app_id, prediction.user_id,
                prediction.model_id, prediction.model_version, prediction.prediction_source,
                prediction.renewal_horizon_days, prediction.churn_probability,
            )
            if stored != stable_fields:
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
                 as_of_at, renewal_due_at, renewal_price_usd
          FROM churn_predictions WHERE prediction_id=%s
        """, (prediction_id,))
        row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Prediction not found")
    out = dict(zip(("prediction_id", "request_id", "app_id", "user_id", "model_id", "model_version",
                    "prediction_source",
                    "churn_probability", "predicted_at", "renewal_horizon_days",
                    "as_of_at", "renewal_due_at", "renewal_price_usd"), row))
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
