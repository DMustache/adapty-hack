# Analytics-owned database scope

This folder belongs to the Analytics agent. Read `services/analytics/AGENTS.md` and your job. Preserve prediction history and idempotency. Keep Grafana read-only. The scaffold uses first-boot SQL; future schema evolution needs versioned migrations and migration tests (no destructive schema reset).
