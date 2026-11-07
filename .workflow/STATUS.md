# Milestone status

- **M0 Foundation** — DONE. Docker QA gate passed on `develop` SHA `e90f6eac05174988b7b4092572920d73376d0df3` (23 tests, Compose, HTTP mock demo and Grafana); promoted to `main`.
- **M1 Churn model adapter** — DONE. Docker QA gate passed on `develop` SHA `592b5061c87f4ce0561c5990f919cbadbd2cca36` (30 tests, Compose, HTTP mock demo and Grafana); promoted to `main`. Live HTTP readback confirmed model version/source provenance.
- **M2 Discount economics & experiment planning** — DONE. Docker QA gate passed on `develop` SHA `40dd474fe879ed4959b4b6f8357cff44bae083be` (41 tests, Compose, HTTP mock demo and Grafana); promoted to `main`. Conservative cent-level allocation and fractional unallocated budget passed independent QA.
- **M3 Analytics + Grafana** — DONE. Docker QA gate passed on `develop` SHA `0d23b0faf619e7684797a8db4c16dc7da964c0dc` (43 tests, Compose, HTTP mock demo, and live PostgreSQL/Grafana QA); promoted to `main`.
- **M4 End-to-end & external handoff** — DONE. Fresh Docker QA gate passed on `develop` SHA `ac3375fb2db248181ea1dc69ade3b1a7a95973fc` (44 tests, Compose, HTTP mock demo, and live PostgreSQL/Grafana QA); promoted to `main`. The synthetic Lumen inspector and leakage checks passed. No compatible external churn baseline was delivered; the demo remains explicitly mock based.
- **M5 PoC model lifecycle** — PLANNED. The pre-model infrastructure wave is specified in `docs/PREMODEL_METRICS.md`: restore the prediction dashboard, improve descriptive and scenario views, and add unit/contract, PostgreSQL/Grafana and fresh Compose checks. M5 has not passed its gate. Lead must freeze churn prediction, risk-cohort, Adapty draft and event interfaces; external ML baseline and documented A/B integration are dependencies. A/B lineage panels and draft creation remain blocked.
- **M6 Standalone frozen model** — PLANNED. Depends on PoC outcomes and validation criteria; model training remains external.

Lead updates status on main. Do not mark any milestone DONE until develop gate passes at its exact commit SHA.
