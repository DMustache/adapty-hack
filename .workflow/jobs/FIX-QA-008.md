---
id: FIX-QA-008
milestone: M5
role: qa
status: READY
depends_on: [FIX-GR-001]
owned_paths: [tests/, scripts/]
---
# FIX-QA-008: Regression gate for offline segment comparison

## Defect reference
- Develop baseline: `28d194b`; Grafana fix: `FIX-GR-001`.
- Expected: dashboard 3 compares two independent, accurately counted offline groups.
- Actual before fix: one shared filter set prevented comparison, and `LIKE` allowed pattern matching.
- Owner: QA.

## Test and acceptance
Extend the M5 offline checkpoint with read-only PostgreSQL checks of the provisioned dashboard SQL after the local seed import. Exercise All, disjoint iOS/Android groups, no-test users, an empty group, and overlapping iOS/US groups. Assert group counts, overlap, empty-group NULL averages/share, and agreement between summary and breakdown group sizes. Verify the two filter sets are independent, use exact SQL-escaped matching, and never output user IDs. Keep the seed archives ignored and local. Commit only `tests/`, `scripts/`, and `handoffs/FIX-QA-008.md`; Lead integrates and runs the exact-SHA checkpoint.
