# Architecture — Smart Retention Offers

Two **custom** FastAPI services:

1. `services/inference`: generic trusted ML adapter boundary, `/v1/predict`, `/v1/retention/plan`; no ML training or churn scoring math. Plan calculator implements algebraic **break-even**, budget ceilings, deterministic randomized experiment allocation and control arm.
2. `services/analytics`: stores immutable scored predictions and immutable experiment plans, actual event ingestion, metrics queries and Grafana-ready PostgreSQL tables. Cannot compute churn or uplift.

Supporting infrastructure: PostgreSQL and Grafana. No Streamlit frontend, Kafka, Kubernetes or arbitrary deserialization. API contracts are Pydantic-generated JSON Schemas, frozen by Lead.

```text
ML researcher -> adapter interface ----------------------.
                                                           v
Synthetic input -> Inference API -> scenario plan --> Analytics API -> Postgres -> Grafana
                                           ^
                                    no realized effect
```

**Revenue economics:** For one upcoming renewal of full-price amount `R`, baseline renewal probability `p` and discount `d`, baseline expected gross renewal revenue is `R·p`; conditional treated renewal probability `q` would yield `R·(1-d)·q`. Equality yields `q_min=p/(1-d)`. This requires an assumption that every treated renewal receives the discount and ignores future renewals, taxes/fees, refunds, offer eligibility and behavior changes. No `q` is estimated here. Hence a plan is **financial-feasibility scenario + randomized experiment proposal**, not a profitable allocation.

**Budget:** allocated `sum(discount · listed price)` rounded to cents is a worst-case face-value discount limit if every selected user renews once. Control has zero discount exposure. Budgets never represent predicted uplift or actual spending.

**Seed data:** `kpotehin/adapty-seed-data-hack` is *synthetic*, single-app Lumen. Its transaction data provides no randomized discount outcomes. Researcher must specify label time windows, eligibility and avoid using post-cutoff transactions in features. Do not presume trained generalizability.

**Workflow:** Lead writes jobs/contracts to main -> sync-plan to develop -> worker worktrees from develop -> Lead integrates -> QA gate on exact develop SHA -> promote to main. Fix loop as new jobs. Root AGENTS short; worktree role-specific AGENTS.

**Current state (2026-11-08):**
- **Inference** serves a researcher-supplied model, `lumen-temporal-catboost`, through the adapter boundary, next to
  the mock. Training and evaluation live in `ml/temporal_churn/` (researcher side), never in the services.
- **Analytics** stores repeated predictions with `as_of_at`, `renewal_due_at` and `renewal_price_usd`, and exposes
  them as Grafana views (`churn_risk_trajectory`, `churn_risk_current`).
- **Usage events** (`usage_events` table, `ml/usage/`) are an optional input not yet read by any service.
- **The Discount Advisor** (`discount_advisor/`) is a separate Streamlit app, not a third service.

Overview: `docs/PROJECT_SUMMARY.md`.
