-- Optional app-usage events (Amplitude / Firebase / CSV exports), loaded by ml/usage/loader.py.
-- Kept separate from the deployed churn model: nothing in the services reads this table yet.
-- user_id is the app's user id as exported, which should equal Adapty's customer_user_id.
-- Init scripts only run on a fresh database volume. For an existing volume, run this file once by hand:
--   docker compose exec -T postgres psql -U adapty_demo -d adapty_demo < postgres/init/004-usage-events.sql

CREATE TABLE IF NOT EXISTS usage_events (
  id BIGSERIAL PRIMARY KEY,
  user_id TEXT NOT NULL,
  event_name TEXT NOT NULL,
  occurred_at TIMESTAMPTZ NOT NULL,
  source TEXT NOT NULL CHECK (source IN ('amplitude', 'firebase', 'csv', 'simulated')),
  source_event_id TEXT,
  loaded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  -- idempotent reloads: the same export loaded twice does not duplicate events
  CONSTRAINT usage_events_dedup UNIQUE (user_id, event_name, occurred_at, source)
);
CREATE INDEX IF NOT EXISTS usage_events_user_time_idx ON usage_events(user_id, occurred_at);

DO $$
BEGIN
  IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'grafana_ro') THEN
    GRANT SELECT ON usage_events TO grafana_ro;
  END IF;
END $$;
