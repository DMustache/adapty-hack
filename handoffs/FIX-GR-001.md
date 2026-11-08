# FIX-GR-001 handoff

Dashboard `behavior-segments` now compares independent Group A/B filters over the same UTC install range. The summary shows group counts, first-day behavior and push opt-in; a separate count shows overlap. All four descriptive breakdowns include both groups and their selected sizes.

Queries use exact string comparisons with Grafana `sqlstring` formatting, `__all__` for All, and `__no_test__` for profiles without an A/B test name. Groups describe synthetic offline users, not verified experiment assignments.

Validation: JSON parsed successfully. All six panel SQL queries executed against the local 50,000-user PostgreSQL import with All, disjoint platform, no-test, empty country, and overlapping platform/country selections. The empty group returned zero users and NULL averages/share. The iOS/Android comparison returned 28,895/21,105 users and zero overlap; iOS versus US returned 10,017 users in both groups.
