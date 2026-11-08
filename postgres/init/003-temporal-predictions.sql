-- Temporal churn predictions: repeated, immutable predictions per subscriber, each tied to the instant its
-- features describe (as_of_at) and the renewal it is about (renewal_due_at).
-- Analytics applies this idempotent migration at startup, including on existing volumes.

ALTER TABLE churn_predictions ADD COLUMN IF NOT EXISTS as_of_at TIMESTAMPTZ;
ALTER TABLE churn_predictions ADD COLUMN IF NOT EXISTS renewal_due_at TIMESTAMPTZ;
ALTER TABLE churn_predictions ADD COLUMN IF NOT EXISTS renewal_price_usd NUMERIC(12,2)
  CHECK (renewal_price_usd IS NULL OR renewal_price_usd > 0);

CREATE INDEX IF NOT EXISTS churn_user_asof_idx
  ON churn_predictions(app_id, user_id, model_id, (COALESCE(as_of_at, predicted_at)));

-- Every prediction with the previous one for the same subscriber and model (ordered by as_of_at, falling back to
-- predicted_at for older rows without as_of_at).
CREATE OR REPLACE VIEW churn_risk_trajectory AS
SELECT
  p.prediction_id, p.app_id, p.user_id, p.model_id, p.model_version, p.prediction_source,
  p.predicted_at, p.as_of_at, p.renewal_due_at,
  COALESCE(p.as_of_at, p.predicted_at) AS effective_at,
  p.churn_probability,
  LAG(p.churn_probability) OVER w AS previous_churn_probability,
  p.churn_probability - LAG(p.churn_probability) OVER w AS churn_probability_change,
  p.renewal_price_usd::double precision AS renewal_price_usd,
  (p.churn_probability * p.renewal_price_usd)::double precision AS expected_revenue_at_risk_usd,
  EXTRACT(EPOCH FROM (p.renewal_due_at - COALESCE(p.as_of_at, p.predicted_at))) / 86400.0 AS days_until_renewal
FROM churn_predictions p
WINDOW w AS (PARTITION BY p.app_id, p.user_id, p.model_id, p.model_version
             ORDER BY COALESCE(p.as_of_at, p.predicted_at), p.predicted_at, p.prediction_id);

-- Latest prediction per subscriber and model version.
CREATE OR REPLACE VIEW churn_risk_current AS
SELECT DISTINCT ON (app_id, user_id, model_id, model_version) *
FROM churn_risk_trajectory
ORDER BY app_id, user_id, model_id, model_version, effective_at DESC, predicted_at DESC, prediction_id DESC;

DO $$
BEGIN
  IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'grafana_ro') THEN
    GRANT SELECT ON churn_risk_trajectory, churn_risk_current TO grafana_ro;
  END IF;
END $$;
