---
id: FIX-GR-002
milestone: M5
role: grafana
status: READY
depends_on: [FIX-GR-001]
owned_paths: [grafana/]
---
# FIX-GR-002: Quote the All selection in offline segment queries

The rendered dashboard fails with PostgreSQL `column "__all__" does not exist` whenever a group contains a mix of selected values and All. Grafana's custom `includeAll` value bypasses SQL escaping, so `:sqlstring` does not quote `__all__`. The previous direct SQL regression quoted every value and missed this.

Replace special Grafana All controls with ordinary query options whose value is `__all__`, so `:sqlstring` quotes them like any other selected value. Keep both independent groups, exact matching, the no-test option, and existing comparison panels. Verify a mixed All/specific selection through Grafana and PostgreSQL logs. Commit only `grafana/` and a handoff; Lead integrates and gates the exact SHA.
