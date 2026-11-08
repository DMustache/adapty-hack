---
id: FIX-GR-001
milestone: M5
role: grafana
status: READY
depends_on: [M5-GR-005, M5-AN-003]
owned_paths: [grafana/]
---
# FIX-GR-001: Compare offline behavior segments

## Defect
- Develop commit SHA: `28d194b` (offline dashboard baseline).
- Gate command: `bash scripts/offline_checkpoint.sh` from the root checkout.
- Expected: A client can configure two independent offline cohorts and compare their sizes and first-day behavior.
- Actual: dashboard 3 has one shared filter set. Its four panels cannot compare two cohorts; `LIKE` matching also treats `%` and `_` in selected values as patterns.
- Reproduction: Open `3. Behavior and Segments — Offline`, select a platform, then try to compare it with another platform on the same dashboard. Only the selected platform remains in every panel.
- Owner: Grafana.
- Regression reference: M5 offline dashboard QA, with direct PostgreSQL checks against the local synthetic seed.

## Scope and acceptance
Keep UID `behavior-segments` and the read-only `adapty-pg` datasource. Add independent Group A and Group B single-select controls for platform, country, channel, onboarding goal, flow, and A/B test name. Both groups share the UTC install range. Each control defaults to All; the test control offers an explicit no-test choice. Match exact values with SQL-escaped Grafana variables, never `LIKE` or raw interpolation.

Show each group's user count, mean first-day edits, mean photos imported, push opt-in count and share, plus the count of users in both groups. Overlap is permitted and labeled. For an empty group, counts are zero and averages/shares are no data. Preserve the descriptive breakdowns for both groups with a Group column and group size visible. Do not display user IDs or describe segments as verified experiment variants or causal effects.

Validate JSON, Grafana provisioning and rendered queries using the ignored local `data/users.csv.gz` through `OFFLINE_DATA_DIR`. Check All, a narrow cohort, no-test, empty cohort, overlap, and both groups' direct SQL totals. Commit only `grafana/` and `handoffs/FIX-GR-001.md`; report the commit SHA and checks. Lead integrates into `develop` and gates the exact SHA.
