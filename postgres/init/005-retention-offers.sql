-- Retention offers: the billing plan of each prediction's renewal (the retention planner needs it) and an index for
-- "latest valid prediction per subscriber" lookups.
-- Init scripts only run on a fresh database volume. For an existing volume, run this file once by hand:
--   docker compose exec -T postgres psql -U adapty_demo -d adapty_demo < postgres/init/005-retention-offers.sql

ALTER TABLE churn_predictions ADD COLUMN IF NOT EXISTS plan_type TEXT
  CHECK (plan_type IS NULL OR plan_type IN ('weekly', 'monthly'));

CREATE INDEX IF NOT EXISTS churn_model_asof_idx
  ON churn_predictions(model_id, app_id, user_id, as_of_at DESC);
