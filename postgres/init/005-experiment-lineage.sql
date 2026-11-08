CREATE TABLE IF NOT EXISTS experiment_lineage (
  kind TEXT NOT NULL CHECK (kind IN ('actual-assignment', 'actual-exposure', 'next-renewal-outcome')),
  app_id TEXT NOT NULL,
  idempotency_key TEXT NOT NULL,
  source TEXT NOT NULL,
  source_event_id TEXT NOT NULL,
  prediction_id TEXT NOT NULL REFERENCES churn_predictions(prediction_id),
  user_id TEXT NOT NULL,
  model_id TEXT NOT NULL,
  model_version TEXT NOT NULL,
  experiment_id TEXT NOT NULL,
  variation_id TEXT NOT NULL,
  assignment_id TEXT NOT NULL,
  exposure_id TEXT,
  event_at TIMESTAMPTZ NOT NULL,
  ingested_at TIMESTAMPTZ NOT NULL,
  payload JSONB NOT NULL,
  PRIMARY KEY (kind, app_id, idempotency_key),
  UNIQUE (kind, source, source_event_id)
);
CREATE INDEX IF NOT EXISTS experiment_lineage_lookup_idx
  ON experiment_lineage (app_id, experiment_id, prediction_id, kind);
CREATE UNIQUE INDEX IF NOT EXISTS experiment_assignment_id_idx
  ON experiment_lineage (app_id, experiment_id, assignment_id)
  WHERE kind = 'actual-assignment';
CREATE UNIQUE INDEX IF NOT EXISTS experiment_exposure_id_idx
  ON experiment_lineage (app_id, experiment_id, exposure_id)
  WHERE kind = 'actual-exposure';

DO $$ BEGIN
  IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'grafana_ro') THEN
    GRANT SELECT ON experiment_lineage TO grafana_ro;
  END IF;
END $$;
