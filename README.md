# Smart Retention Offers — Adapty Hackathon Infrastructure

**Scope:** infrastructure for an *externally developed* churn model and a **scenario-based retention experiment planner**. The dataset has **no observed response to discounts**, so **no uplift predictions, realized savings, or optimal discounts** are claimed. The services never train or score on their own: churn models are trained on the researcher side (`ml/`) and reach the services only as a checksummed artifact through the `ModelAdapter` boundary.

## Two custom services

```text
External churn researcher -> trusted ModelAdapter -> Inference/Planning API :8001
                                                 |        |
                         mock + temporal CatBoost (ml/)  break-even / budget experiment planner
                                                 |        |
                                                 +-- structured results --> Analytics API :8002
                                                                         |
                                                                      PostgreSQL
                                                                         |
                                                              Grafana (read-only) :3000
```

Service A loads the eventual model through a narrow adapter, exposes `/v1/predict`, and offers `/v1/retention/plan` using *non-ML algebra*. Service B stores prediction/experiment snapshots and exposes queried data. PostgreSQL/Grafana are infrastructure, not services developed by agents.

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
- Grafana: `http://localhost:3000/d/smart-retention`

Demo uses mock fixture risks for 12 users. All outputs are clearly labeled. PostgreSQL initialization scripts run on **new volumes only**; if replacing the old Demand Score local demo with the same database volume, explicitly remove the **demo-only** old volume (`docker compose down -v` — destructive) before starting.

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

The infrastructure scaffold now also serves a **researcher-supplied temporal churn model** (validated on the synthetic Lumen data only), stores repeated predictions with `as_of_at`/`renewal_due_at`, and ships the **Discount Advisor** app and optional **usage-data** support. It is still not a proven discount optimizer and not a production Adapty integration. Unit/contract tests are supplied (93 in `tests/`, plus the Discount Advisor's own suite); container E2E depends on Docker availability and has not been run on the development machine.

**Full summary of everything built:** [docs/PROJECT_SUMMARY.md](docs/PROJECT_SUMMARY.md).

### Added components (2026-11-08)

| Component | Where | Notes |
|---|---|---|
| Temporal churn model (CatBoost, point-in-time snapshots) | `ml/temporal_churn/` (training, evaluation), `services/inference/models/temporal_catboost/` (artifact), `services/inference/app/adapters/temporal_catboost.py` | Registered as `lumen-temporal-catboost` next to the mock when the artifact is present. See `docs/TEMPORAL_CHURN.md` |
| Repeated predictions + risk trajectories | `postgres/init/003-temporal-predictions.sql`, `GET /v1/metrics/churn-trajectory`, Grafana `http://localhost:3000/d/churn-risk-trajectory` | Optional contract fields `as_of_at`, `renewal_due_at`, `renewal_price_usd` |
| Replay snapshots through the API | `python scripts/score_temporal_snapshots.py --data-dir …/data/offline` | Local services only; no Adapty calls |
| Optional usage events | `postgres/init/004-usage-events.sql`, `ml/usage/` | Not used by the deployed model. See `docs/USAGE_FEATURES.md` |
| Discount Advisor (Streamlit) | `discount_advisor/` | Separate app, not a service. See `discount_advisor/README.md` |

**Existing database volumes:** init scripts only run on new volumes. Apply the new ones once by hand:

```bash
docker compose exec -T postgres psql -U adapty_demo -d adapty_demo < postgres/init/003-temporal-predictions.sql
docker compose exec -T postgres psql -U adapty_demo -d adapty_demo < postgres/init/004-usage-events.sql
```

The inference image now needs `catboost` (in `services/inference/requirements.txt`), so rebuild with
`docker compose up --build`.
