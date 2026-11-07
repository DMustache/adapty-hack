# Grafana visualization scope

This folder belongs to the Grafana visualization worker. Read `.workflow/roles/grafana.md` and your assigned job. Own only `grafana/`; provision dashboards from files and query PostgreSQL as read-only. Show stored predictions and scenario experiments with UTC timestamps and clear mock/scenario labels. If a metric is missing, display no data; never generate a fabricated line or claim measured savings. Request missing fields from Lead; do not edit `services/analytics/`, `postgres/`, or `contracts/`.
