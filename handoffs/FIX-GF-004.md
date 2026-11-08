# FIX-GF-004 — Grafana demo readiness

## Result

- Five provisioned dashboards; all 27 panel queries returned at least one row through Grafana's PostgreSQL datasource API on the isolated demo stack.
- Imported the local synthetic Lumen snapshot: 50,000 users, 29,794 transactions, and two source inventory records.
- Ran the fixed-model M8 synthetic walkthrough with app `lumen-m8-8ad6fdfeae`: three simulated assignments, two exposures, one mature outcome. The selected subscriber's stored risk change is −0.0860526535.
- `grafana_ro` can SELECT from `offline_users` and cannot INSERT. All dashboard SQL remains read-only, and Grafana reports UTC.
- Browser screenshots after load confirmed populated Model Health, Business and Revenue, and Churn Risk dashboards. Behavior and Campaign panel queries passed; their headless browser screenshots were interrupted or captured during loading, so visual inspection remains unconfirmed.

| Dashboard | Populated panels |
| --- | ---: |
| Data and Model Health | 4/4 |
| Business and Revenue | 4/4 |
| Behavior and Segments | 6/6 |
| Campaign Tracking | 4/4 |
| Churn Risk Over Time | 9/9 |

The risk dashboard now calls panel 7 **Largest risk changes**, shows signed stored changes ordered by absolute magnitude, formats subscriber counts as counts, and places dollar values on a dollar axis in the daily chart. It keeps synthetic, simulated, and hypothetical labels.

## Demo links and environment

The isolated worktree stack remains available at `127.0.0.2` because the root project's containers already occupy `127.0.0.1` ports. The temporary Compose override is `/tmp/fix-gr-004-ports.yaml`; it maps Grafana to `127.0.0.2:3000`, inference to `127.0.0.2:8001`, and analytics to `127.0.0.2:8002`. The root project's `127.0.0.1` stack has an older database without the offline tables and was left unchanged.

- Model Health: http://127.0.0.2:3000/d/model-health
- Business and Revenue: http://127.0.0.2:3000/d/business-revenue
- Behavior and Segments: http://127.0.0.2:3000/d/behavior-segments
- Campaign Tracking: http://127.0.0.2:3000/d/smart-retention
- Risk and simulated lineage: http://127.0.0.2:3000/d/churn-risk-trajectory?var-source=external&var-app=lumen-m8-8ad6fdfeae&var-model=lumen-temporal-catboost&var-version=1.0.0&var-user=b4b6e63d5ec9075aab709ee4a159d8b5&from=1783246073000&to=now&refresh=5s

The worktree's ignored `.agent-runtime/fix-gr-004-demo.json` holds the M8 run report. If this stack is stopped, restart it with the same override and offline data directory; the named PostgreSQL volume retains the imported snapshot and M8 data. The temporary override enables anonymous Viewer access solely for local visual checks.

## Checks

- Grafana `/api/dashboards/uid/*`: all five UIDs provisioned.
- Grafana `/api/ds/query`: 27/27 populated with demo filters, no query errors.
- Targeted static tests: 5 passed, 1 live test deselected.
- Dashboard JSON parsing and `git diff --check`: passed.

Before a standard `localhost` presentation, Lead must integrate this branch into `develop`, rebuild the standard stack, import the offline snapshot, run M8, and update the walkthrough's panel 7 description. This worktree follows the Grafana worker ownership boundary.
