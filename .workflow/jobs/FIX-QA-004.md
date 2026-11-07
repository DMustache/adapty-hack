---
id: FIX-QA-004
milestone: M3
role: qa
status: READY
depends_on: []
owned_paths:
  - scripts/smoke_demo.py
---
# FIX-QA-004: Wait for provisioned Grafana dashboard

## Failing gate
`PATH=.worktrees/develop/.venv/bin:$PATH bash scripts/gate.sh M3` failed on `develop` SHA `f6c2a2d17d93a78c5b029150e168deab5f18ba83`. The log `.worktrees/develop/.agent-runtime/gates/M3.log` shows HTTP 404 from `GET /api/dashboards/uid/smart-retention` immediately after Grafana `/api/health` reported ready. The same `python scripts/smoke_demo.py` passed seconds later. Expected: bounded startup readiness waits until file-provisioned dashboard exists. Actual: dashboard request is made once and aborts on transient 404.

## Work
Change only `scripts/smoke_demo.py` to retry dashboard 404 during startup for a bounded period. Keep the existing health and dashboard UID assertions. Do not retry authentication errors or hide persistent failures. Add a focused verification of transient 404 and non-retryable errors if practical.

## Acceptance and handoff
Smoke tolerates provisioning delay but fails when the dashboard remains unavailable or credentials are wrong. Run targeted checks, commit on `fix/FIX-QA-004`, write `handoffs/FIX-QA-004.md`, and send Lead SHA. Lead integrates and reruns the M3 gate.
