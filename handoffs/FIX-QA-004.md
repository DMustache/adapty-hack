# FIX-QA-004 handoff

- Updated `scripts/smoke_demo.py` to wait for the provisioned Grafana dashboard after Grafana health becomes ready. Only HTTP 404 is retried, for at most 40 attempts; authentication failures and malformed dashboards still fail immediately.
- Focused mocked checks passed: a 404 followed by the dashboard succeeds after one retry; HTTP 401 stops after one request; 40 persistent 404s fail after 39 sleeps. `git diff --check` passed.
- Existing Ruff findings in this file remain outside the fix: `EXE001` (shebang without executable bit) and `UP012` (existing explicit UTF-8 encoding in Basic Auth). No new lint finding was introduced.
- Blockers: none. Lead should integrate and rerun the M3 gate on the exact `develop` SHA.
