---
id: FIX-QA-009
milestone: M5
role: qa
status: READY
depends_on: [FIX-GR-002]
owned_paths: [tests/, scripts/]
---
# FIX-QA-009: Catch Grafana All interpolation regression

Extend the offline dashboard checkpoint to reject `includeAll` custom values for the Group A/B controls and require an ordinary All query option. Exercise the user's mixed All/specific flow comparison as well as existing cohort cases. Keep checks read-only and local to QA-owned paths. Commit a handoff; Lead integrates and gates the exact SHA.
