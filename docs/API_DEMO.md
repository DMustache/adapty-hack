# Smart Retention Offers API demo

This project adds **two local APIs alongside Adapty**. They do not replace the Adapty SDK, dashboard, or server-side API. Adapty manages subscription products, paywalls or flows, placements, and live A/B tests. Our APIs accept a churn probability, calculate a reviewable retention experiment scenario, and store the inputs and proposal for inspection. There is no live Adapty write path in this milestone.

Adapty also has [A/B test predictions](https://adapty.io/docs/predictions-in-ab-tests), which forecast long-term revenue for test variants. That is a different prediction target from this project's **per-subscriber churn probability**. The current churn probability comes from a fixed mock fixture; an external model has not been loaded.

## OpenAPI

| Service | Interactive docs | Live spec | Checked-in M4 snapshot |
| --- | --- | --- | --- |
| Inference and planning | <http://localhost:8001/docs> | <http://localhost:8001/openapi.json> | [`openapi/inference.openapi.json`](openapi/inference.openapi.json) |
| Analytics | <http://localhost:8002/docs> | <http://localhost:8002/openapi.json> | [`openapi/analytics.openapi.json`](openapi/analytics.openapi.json) |

The snapshots describe the tested M4 implementation. The live URLs reflect the running code. Regenerate snapshots from a running build with `curl -fsS http://localhost:8001/openapi.json | jq -S . > docs/openapi/inference.openapi.json` and the equivalent command for port 8002.

## Why each API exists

| Our method | Input → output | Purpose |
| --- | --- | --- |
| `GET :8001/v1/models` and `GET :8001/v1/models/{model_id}/schema` | Model ID → available adapter and feature schema | Discover the mock adapter now; provide a narrow boundary for a separately delivered model later. |
| `POST :8001/v1/predict` | Subscriber ID, model ID, horizon, features → labeled probability, model version, prediction ID | Record one risk input with provenance. The mock returns fixture values; this service does not train or infer a churn model. It forwards the result to analytics. |
| `POST :8001/v1/retention/plan` | Candidate risks, prices, budget, discounts → proposed arms, maximum exposure, break-even hurdles | Compare hypothetical economics and preserve a control arm before an operator designs a real test. It forwards the proposal to analytics; it does not activate offers. |
| `POST :8002/v1/ingest/predictions` and `GET :8002/v1/predictions/{id}` | Prediction → stored prediction | Internal persistence and readback; the inference API normally calls ingest. |
| `POST :8002/v1/ingest/experiments` and `GET :8002/v1/experiments/{id}` | Proposal → immutable stored proposal | Internal persistence and review; a changed retry with the same experiment ID is rejected. |
| `GET :8002/v1/metrics/churn-risk` | Optional `app_id` → stored risk points | Read data for checks and Grafana. |
| `POST :8002/v1/ingest/actuals` | Explicit observed metric and UTC timestamp → stored/duplicate status | Keep actual observations separate from hypothetical proposals. No Adapty event feed is connected yet. |

Both services also expose `GET /health`. These endpoints are project-specific; their `/v1` paths are **not Adapty API paths**. Adapty's documented [segments](https://adapty.io/docs/segments), [profile updates](https://adapty.io/docs/api-adapty/operations/updateProfile), and [A/B tests](https://adapty.io/docs/developer-cli-ab-tests) are the later integration surface. A live Adapty test would own its arm assignment; the planner's per-user arms are only a proposal and must not be sent as a second assignment system. See [the integration boundary](ADAPTY_INTEGRATION.md).

## Run a manual example

From the repository root, start one Compose project with `docker compose up --build -d`. If the tested `.worktrees/develop` project is already running, use that project instead of starting another one on the same ports. Open the interactive docs above, or use these requests:

```bash
DEMO_ID="api-demo-$(date -u +%s)-$RANDOM"
curl -sS http://localhost:8001/v1/models | jq
jq -n --arg id "$DEMO_ID" '{request_id:$id, app_id:"lumen-demo", user_id:"demo-u01", model_id:"mock-churn-v1", renewal_horizon_days:30, features:{event_count:4}}' \
  | curl -sS http://localhost:8001/v1/predict -H 'Content-Type: application/json' -d @- \
  | tee /tmp/prediction.json | jq
curl -sS "http://localhost:8002/v1/predictions/$(jq -r .prediction_id /tmp/prediction.json)" | jq
```

The prediction response reports `prediction_source: "mock"`, `model_version: "0.0.0-mock"`, and `churn_probability: 0.8` for `demo-u01`. The readback contains the same prediction ID and risk. Use a new `request_id` for another decision.

```bash
jq -n --arg id "$DEMO_ID" '{app_id:"lumen-demo", experiment_id:$id, budget_usd:2, control_share:0.34, discounts:[0.1,0.2], candidates:[{user_id:"demo-u01",churn_probability:0.8,renewal_price_usd:9.99,plan_type:"monthly"},{user_id:"demo-u02",churn_probability:0.45,renewal_price_usd:9.99,plan_type:"monthly"},{user_id:"demo-u03",churn_probability:0.25,renewal_price_usd:9.99,plan_type:"monthly"}]}' \
  | curl -sS http://localhost:8001/v1/retention/plan -H 'Content-Type: application/json' -d @- \
  | tee /tmp/plan.json | jq
curl -sS "http://localhost:8002/v1/experiments/$DEMO_ID" | jq
```

Inspect `assignments`, `max_allocated_discount_exposure_usd`, `unallocated_budget_usd`, and `required_absolute_uplift`. The `modeled_discount_uplift` field is `false`; the hurdle is algebraic, not a measured treatment effect. Change `experiment_id` when changing a proposal because stored proposals are immutable. Open <http://localhost:3000/d/smart-retention> to see the stored scenario in Grafana.

For a complete 12-user run, execute `python scripts/smoke_demo.py` in the Compose project's directory. It generates unique IDs and checks the prediction, persistence, planning, and dashboard path. Its success message does not mean offers were delivered or Adapty was changed.
