CREATE TABLE IF NOT EXISTS churn_predictions (
  prediction_id TEXT PRIMARY KEY,
  request_id TEXT NOT NULL,
  app_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  model_id TEXT NOT NULL,
  model_version TEXT NOT NULL,
  prediction_source TEXT NOT NULL CHECK (prediction_source IN ('mock', 'external')),
  predicted_at TIMESTAMPTZ NOT NULL,
  renewal_horizon_days INTEGER NOT NULL CHECK (renewal_horizon_days > 0),
  churn_probability DOUBLE PRECISION NOT NULL CHECK (churn_probability >= 0 AND churn_probability <= 1),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS churn_app_time_idx ON churn_predictions(app_id, predicted_at);

CREATE TABLE IF NOT EXISTS retention_experiments (
  experiment_id TEXT PRIMARY KEY,
  app_id TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL,
  budget_usd NUMERIC(16,2) NOT NULL CHECK (budget_usd >= 0),
  max_exposure_usd NUMERIC(16,2) NOT NULL CHECK (max_exposure_usd >= 0),
  payload JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS retention_experiments_app_time_idx ON retention_experiments(app_id, created_at);

CREATE TABLE IF NOT EXISTS actual_observations (
  observation_id TEXT PRIMARY KEY,
  app_id TEXT NOT NULL,
  metric_name TEXT NOT NULL,
  metric_value DOUBLE PRECISION NOT NULL,
  observed_at TIMESTAMPTZ NOT NULL,
  dimensions JSONB NOT NULL DEFAULT '{}'::jsonb,
  source TEXT NOT NULL CHECK (source IN ('demo','external')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS actuals_app_time_idx ON actual_observations(app_id, observed_at);
