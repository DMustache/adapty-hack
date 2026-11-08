-- Additive bridge from persisted predictions to planner candidates.
ALTER TABLE churn_predictions ADD COLUMN IF NOT EXISTS plan_type TEXT
  CHECK (plan_type IS NULL OR plan_type IN ('weekly', 'monthly'));

CREATE INDEX IF NOT EXISTS churn_candidate_lookup_idx
  ON churn_predictions(app_id, model_id, model_version, user_id, as_of_at DESC, predicted_at DESC);
