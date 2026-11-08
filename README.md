# Smart Retention Offers — Adapty Hackathon Infrastructure

**Scope:** infrastructure for an *externally developed* churn model and a **scenario-based retention experiment planner**. The dataset has **no observed response to discounts**, so **no uplift predictions, realized savings, or optimal discounts** are claimed. Do not train an ML model in this repository.

## Two custom services

```text
External churn researcher -> trusted ModelAdapter -> Inference/Planning API :8001
                                                 |        |
                              mock + fixed CatBoost      break-even / budget experiment planner
                                                 |        |
                                                 +-- structured results --> Analytics API :8002
                                                                         |
                                                                      PostgreSQL
                                                                         |
                                                              Grafana (read-only) :3000
```

Service A loads the fixed external model or the separate mock through a narrow adapter, exposes `/v1/predict`, and offers `/v1/retention/plan` using *non-ML algebra*. Service B stores prediction/experiment snapshots and exposes queried data. PostgreSQL/Grafana are infrastructure, not services developed by agents.

### What is / is not modeled

- `churn_probability`: **supplied by external model**, or deterministic static fixture (`prediction_source=mock`). Not calculated by our backend.
- `expected revenue at risk`: sum of `price × churn_probability` for a single specified next renewal per customer, contingent on correct calibration and aligned horizon. Not realized loss.
- Discount break-even: for baseline renewal probability `p`, discount `d`, the offer renewal rate must be at least `p / (1-d)` for equal *immediate gross renewal revenue*; if greater than 1, break-even is impossible under this simple comparison.
- Budget: hard upper bound on **maximum face-value discount exposure** for allocated arms. Not actual spending, causal effect, or expected uplift.
- Randomized holdout: controls and discount arms are an experiment proposal, **not automatic offer activation**. No Adapty write API is used.

### Run locally

```bash
cp .env.example .env
docker compose up --build -d
python scripts/smoke_demo.py
```

With [mise](https://mise.jdx.dev/), `mise.toml` selects Python 3.12.16 and provides the same local workflow:

```bash
mise install
mise run setup
mise run test
mise run up
mise run smoke
mise run down
```

`mise run lint` checks the Python files with Ruff. Docker Compose is still required for the service and smoke tasks.

- Inference/Planner OpenAPI: `http://localhost:8001/docs`
- Analytics OpenAPI: `http://localhost:8002/docs`
- Grafana model inventory: `http://localhost:3000/d/model-health`
- Grafana risk and simulated lineage: `http://localhost:3000/d/churn-risk-trajectory`
- Grafana offline campaign fields: `http://localhost:3000/d/smart-retention`

See the [API demo guide](docs/API_DEMO.md) for request and response examples, checked-in OpenAPI snapshots, and how these custom methods relate to Adapty.

For the exact route flow, model and event contracts, provenance of every Grafana panel, and a staged presentation command, read the [Russian system and dashboard guide](docs/SYSTEM_FLOW_AND_DASHBOARDS_RU.md).

The `smoke_demo.py` check uses mock fixture risks for 12 users; `scripts/m5_demo.py` shows the fixed model with synthetic inputs and simulated experiment events. PostgreSQL initialization scripts run on **new volumes only**; analytics applies later migrations at startup. If replacing an old demo database, inspect the volume before deleting it (`docker compose down -v` is destructive).

### Offline hackathon dataset

Source: `https://github.com/kpotehin/adapty-seed-data-hack` (fictional Lumen AI Photo Editor, 50k users, ~30k synthetic transactions). It is **not packaged** inside this repository. Download separately:

```bash
git clone --depth 1 https://github.com/kpotehin/adapty-seed-data-hack.git /tmp/adapty-seed-data-hack
python scripts/inspect_seed_data.py /tmp/adapty-seed-data-hack/data/offline
```

Dataset inspector verifies gzipped CSV files and reports columns/row counts; it deliberately **does not train or create historical churn labels**. Researcher owns leakage-safe cohort/label design. Data only represents one simulated app, not validated production evidence.

### Git worktrees: Lead -> Worker -> Develop QA -> Main

```bash
bash scripts/bootstrap.sh             # root on main; creates .worktrees/develop
bash scripts/sync-plan.sh             # committed Lead tasks/contracts: main -> develop
bash scripts/spawn-job.sh M1-BE-001   # fork isolated task worktree from develop
bash scripts/spawn-job.sh M1-QA-001   # QA works in parallel from frozen contracts
# Launch coding-agent sessions in paths printed by spawn-job; scripts do NOT auto-launch AI agents.
bash scripts/integrate-job.sh M1-BE-001
bash scripts/integrate-job.sh M1-QA-001
bash scripts/gate.sh M1               # pytest + docker compose + HTTP/Grafana E2E on develop SHA
bash scripts/promote-milestone.sh M1  # only if tested SHA still matches
```

Failed gate? Lead writes `.workflow/jobs/FIX-*.md` on `main`, syncs plan to develop, spawns specific fix worktree, merges it, reruns gate. No workers commit directly to `develop` or `main`.

See `.workflow/README.md`, `docs/ARCHITECTURE.md`, and `docs/MODEL_HANDOFF.md`.

### Project state

This is a **runnable synthetic hackathon demo**. It includes the unchanged, externally supplied `lumen-temporal-catboost` 1.0.0 artifact alongside a separate mock adapter, plus simulated experiment lineage. The demo does not establish real-customer calibration, measured discount uplift, or a production Adapty integration. See [M5 demo](docs/M5_DEMO.md), the [M6 walkthrough](docs/M6_WALKTHROUGH_RU.md), and [M6 data requirements](docs/M6_DATA_REQUIREMENTS.md); container E2E depends on Docker availability.
