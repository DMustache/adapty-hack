# Milestone status

- **M0 Foundation** — DONE. Docker QA gate passed on `develop` SHA `e90f6eac05174988b7b4092572920d73376d0df3` (23 tests, Compose, HTTP mock demo and Grafana); promoted to `main`.
- **M1 Churn model adapter** — DONE. Docker QA gate passed on `develop` SHA `592b5061c87f4ce0561c5990f919cbadbd2cca36` (30 tests, Compose, HTTP mock demo and Grafana); promoted to `main`. Live HTTP readback confirmed model version/source provenance.
- **M2 Discount economics & experiment planning** — READY after contracts.
- **M3 Analytics + Grafana** — READY after contract freeze.
- **M4 End-to-end & external handoff** — BLOCKED on M1-M3 integration; no real ML required for mock demo.

Lead updates status on main. Do not mark any milestone DONE until develop gate passes at its exact commit SHA.
