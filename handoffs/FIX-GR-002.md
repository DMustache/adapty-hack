# FIX-GR-002 handoff

PostgreSQL logs showed Grafana interpolating a custom All value as unquoted `__all__`, causing every panel to fail when a selected filter was mixed with All. Each Group A/B variable now returns an ordinary `All` option with value `__all__`; Grafana applies `:sqlstring` to this value and to specific choices. No panel SQL or cohort definitions changed.

The dashboard JSON parses and remains provisioned under UID `behavior-segments`. QA will check actual cohort totals and the absence of Grafana custom All controls in the exact-SHA offline checkpoint.
