# Milestone status

- **M0 Foundation** — DONE. Docker QA gate passed on `develop` SHA `e90f6eac05174988b7b4092572920d73376d0df3` (23 tests, Compose, HTTP mock demo and Grafana); promoted to `main`.
- **M1 Churn model adapter** — DONE. Docker QA gate passed on `develop` SHA `592b5061c87f4ce0561c5990f919cbadbd2cca36` (30 tests, Compose, HTTP mock demo and Grafana); promoted to `main`. Live HTTP readback confirmed model version/source provenance.
- **M2 Discount economics & experiment planning** — DONE. Docker QA gate passed on `develop` SHA `40dd474fe879ed4959b4b6f8357cff44bae083be` (41 tests, Compose, HTTP mock demo and Grafana); promoted to `main`. Conservative cent-level allocation and fractional unallocated budget passed independent QA.
- **M3 Analytics + Grafana** — DONE. Docker QA gate passed on `develop` SHA `0d23b0faf619e7684797a8db4c16dc7da964c0dc` (43 tests, Compose, HTTP mock demo, and live PostgreSQL/Grafana QA); promoted to `main`.
- **M4 End-to-end & external handoff** — READY after M1-M3 integration; no real ML required for mock demo.
- **M5 PoC model lifecycle** — PLANNED. Lead must freeze churn prediction, risk-cohort, Adapty draft and event interfaces; external ML baseline and documented A/B integration are dependencies. Churn Grafana and Adapty draft jobs are tracked in M5.
- **M6 Standalone frozen model** — PLANNED. Depends on PoC outcomes and validation criteria; model training remains external.

Lead updates status on main. Do not mark any milestone DONE until develop gate passes at its exact commit SHA.
