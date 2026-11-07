"""Database-backed ingestion checks. Run against a disposable PostgreSQL database."""

import concurrent.futures
import os
import unittest
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import HTTPException

from shared.contracts.models import ActualObservation, ChurnPredictionResult, RetentionPlanResult
from services.analytics.app.main import (
    db_connect,
    get_experiment,
    get_prediction,
    ingest_actual,
    ingest_experiment,
    ingest_prediction,
)


@unittest.skipUnless(os.environ.get("DATABASE_URL"), "DATABASE_URL is required")
class IngestionTests(unittest.TestCase):
    def prediction(self, **changes):
        data = {
            "prediction_id": str(uuid4()),
            "request_id": "request-1",
            "app_id": "app-1",
            "user_id": "pseudonymous-user-1",
            "model_id": "external-model",
            "model_version": "1.2",
            "prediction_source": "external",
            "predicted_at": datetime.now(timezone.utc),
            "renewal_horizon_days": 30,
            "churn_probability": 0.25,
        }
        data.update(changes)
        return ChurnPredictionResult.model_validate(data)

    def experiment(self, **changes):
        data = {
            "experiment_id": str(uuid4()),
            "app_id": "app-1",
            "request_fingerprint": "a" * 64,
            "created_at": datetime.now(timezone.utc),
            "budget_usd": 100.0,
            "max_allocated_discount_exposure_usd": 0.0,
            "expected_baseline_revenue_at_risk_usd": 20.0,
            "unallocated_budget_usd": 100.0,
            "assignments": [{
                "user_id": "pseudonymous-user-1",
                "plan_type": "monthly",
                "arm": "control",
                "discount_fraction": 0.0,
                "max_discount_exposure_usd": 0.0,
                "renewal_price_usd": 10.0,
                "expected_revenue_at_risk_usd": 2.0,
                "baseline_renewal_probability": 0.8,
            }],
            "disclaimer": "Hypothetical scenario; no observed effect.",
        }
        data.update(changes)
        return RetentionPlanResult.model_validate(data)

    def actual(self, **changes):
        data = {
            "observation_id": str(uuid4()),
            "app_id": "app-1",
            "metric_name": "renewals",
            "metric_value": 1.0,
            "observed_at": datetime.now(timezone.utc),
            "dimensions": {"cohort": "test"},
            "source": "demo",
        }
        data.update(changes)
        return ActualObservation.model_validate(data)

    def test_prediction_retries_and_readback(self):
        original = self.prediction()
        self.assertEqual(ingest_prediction(original)["status"], "stored")
        retry = original.model_copy(update={"predicted_at": original.predicted_at + timedelta(seconds=1)})
        self.assertEqual(ingest_prediction(retry)["status"], "duplicate")
        stored = get_prediction(original.prediction_id)
        self.assertEqual(stored["predicted_at"], original.predicted_at)
        for field in ("request_id", "model_id", "model_version", "prediction_source",
                      "renewal_horizon_days", "churn_probability"):
            self.assertEqual(stored[field], getattr(original, field))
        for field, value in (("request_id", "request-2"), ("model_version", "2"),
                             ("prediction_source", "mock"), ("renewal_horizon_days", 7),
                             ("churn_probability", 0.5)):
            with self.subTest(field=field), self.assertRaises(HTTPException) as caught:
                ingest_prediction(original.model_copy(update={field: value}))
            self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(get_prediction(original.prediction_id), stored)

    def test_experiment_retries_conflicts_and_readback(self):
        original = self.experiment()
        self.assertEqual(ingest_experiment(original)["status"], "stored")
        self.assertEqual(ingest_experiment(original)["status"], "duplicate")
        stored = get_experiment(original.experiment_id)
        self.assertEqual(stored, original.model_dump(mode="json"))
        self.assertEqual(stored["assignments"][0]["arm"], "control")
        for field, value in (("request_fingerprint", "b" * 64),
                             ("created_at", original.created_at + timedelta(seconds=1)),
                             ("budget_usd", 110.0), ("disclaimer", "Changed scenario")):
            with self.subTest(field=field), self.assertRaises(HTTPException) as caught:
                ingest_experiment(original.model_copy(update={field: value}))
            self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(get_experiment(original.experiment_id), stored)

    def test_concurrent_same_id(self):
        for make, ingest, table, id_field in (
            (self.prediction, ingest_prediction, "churn_predictions", "prediction_id"),
            (self.experiment, ingest_experiment, "retention_experiments", "experiment_id"),
        ):
            with self.subTest(table=table):
                item = make()
                with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                    results = list(pool.map(ingest, [item] * 8))
                self.assertEqual([r["status"] for r in results].count("stored"), 1)
                self.assertEqual([r["status"] for r in results].count("duplicate"), 7)
                with db_connect() as conn, conn.cursor() as cur:
                    cur.execute(f"SELECT count(*) FROM {table} WHERE {id_field} = %s", (getattr(item, id_field),))
                    self.assertEqual(cur.fetchone()[0], 1)

    def test_concurrent_conflicting_id(self):
        for original, changed, ingest in (
            (self.prediction(), {"churn_probability": 0.5}, ingest_prediction),
            (self.experiment(), {"budget_usd": 110.0}, ingest_experiment),
        ):
            with self.subTest(kind=type(original).__name__):
                conflicting = original.model_copy(update=changed)
                def attempt(item):
                    try:
                        return ingest(item)["status"]
                    except HTTPException as exc:
                        return exc.status_code

                with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                    results = list(pool.map(attempt, (original, conflicting)))
                self.assertCountEqual(results, ("stored", 409))

    def test_actual_retries_and_conflicts_are_isolated_from_scenarios(self):
        original = self.actual()
        self.assertEqual(ingest_actual(original)["status"], "stored")
        self.assertEqual(ingest_actual(original)["status"], "duplicate")
        for field, value in (
            ("metric_value", 2.0),
            ("observed_at", original.observed_at + timedelta(seconds=1)),
            ("dimensions", {"cohort": "changed"}),
            ("source", "external"),
        ):
            with self.subTest(field=field), self.assertRaises(HTTPException) as caught:
                ingest_actual(original.model_copy(update={field: value}))
            self.assertEqual(caught.exception.status_code, 409)
        with db_connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT metric_value, dimensions FROM actual_observations WHERE observation_id = %s",
                        (original.observation_id,))
            self.assertEqual(cur.fetchone(), (1.0, {"cohort": "test"}))
            cur.execute("SELECT count(*) FROM retention_experiments WHERE experiment_id = %s",
                        (original.observation_id,))
            self.assertEqual(cur.fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
