# Churn predictor I/O and Adapty A/B handoff

This is the target integration for the external churn predictor. The application
services do not train or update model weights. `origin/model-implementation` at
`253b5bd65cd71c69c5b2308ae4e0b097a2e31095` currently contains only
`discount_advisor/`, a synthetic-data cohort experiment advisor. It has no
churn inference entrypoint, trained weights, or per-subscriber churn output.
That branch cannot yet be plugged into the interface below; the external ML
owner must deliver the churn predictor described in `MODEL_HANDOFF.md`.

## Predictor input and output

The existing infrastructure endpoint is `POST /v1/predict`. Its version 1
request and response are frozen in `contracts/schemas/churn-prediction-*.json`.
A request represents **one currently active weekly or monthly subscriber** at
one decision time:

```json
{
  "schema_version": "1.0",
  "request_id": "decision-123",
  "app_id": "lumen-demo",
  "user_id": "pseudonymous-user-123",
  "model_id": "external-churn",
  "renewal_horizon_days": 30,
  "context": {"platform": "ios", "feature_cutoff_at": "2026-11-07T12:00:00Z"},
  "features": {"<model-owned feature>": "<cutoff-safe value>"}
}
```

The exact feature keys, types, null policy, horizon semantics and model ID
belong to the external ML delivery. Do not copy `discount_advisor` install or
receipt aggregates into these features. The trusted `ModelAdapter` loads the
approved model version and validates `features` against its input schema. Its
`predict(user_id, features, context)` returns one finite calibrated probability
in `[0,1]`; if calibration is absent, the external owner must provide a new
score contract instead of calling the number a probability.

The inference service returns and persists:

```json
{
  "schema_version": "1.0",
  "prediction_id": "<stable ID for this decision request>",
  "request_id": "decision-123",
  "app_id": "lumen-demo",
  "user_id": "pseudonymous-user-123",
  "model_id": "external-churn",
  "model_version": "<approved immutable version>",
  "prediction_source": "external",
  "predicted_at": "2026-11-07T12:00:01Z",
  "renewal_horizon_days": 30,
  "churn_probability": 0.42
}
```

Retries keep `request_id` and `prediction_id`; conflicting feature/model
content must be rejected rather than silently replacing an earlier prediction.
All timestamps are UTC. The owner must also supply model metadata: trusted
artifact or endpoint, checksum, runtime, version, input schema, target label,
training-data cutoff, calibration report and deterministic fixture. A candidate
version may be evaluated separately but must not replace the active version.

## Prediction to experiment

1. Persist every prediction with model version and source. Grafana reads it
   from analytics; `mock` and `external` are separate series.
2. An approved policy selects eligible subscribers and records the prediction
   ID, decision time, version, horizon, price and policy version. No arbitrary
   risk threshold is chosen by this infrastructure. The existing
   `POST /v1/retention/plan` may calculate a **proposal** and budget exposure;
   it is not evidence that an offer was delivered.
3. For a regular Adapty placement A/B test, publish a **frozen risk cohort**
   to an agreed profile custom attribute, such as `churn_cohort`, using an
   explicit mapping from our pseudonymous `user_id` to Adapty's identified
   customer user ID. Pin the cohort's model and policy versions for the test.
   Adapty profile updates use its documented server API with `ADAPTY_SECRET`
   kept server-side; require a dry run, idempotency, retries and audit logs.
   Allow for profile and segment propagation delay. An unset attribute must
   never imply low risk.
4. An Adapty segment filters that cohort and eligible subscription state.
   Create a **draft** flow A/B test for that segment on one placement, with a
   verified published control flow and treatment flow. The treatment's actual
   store product/offer must match the reviewed discount scenario. Check for a
   running test on the same placement/audience before any activation.
5. Adapty owns arm randomization for this test. Do not also deliver the
   planner's per-user random arm; that would produce two inconsistent
   assignments. Persist Adapty test/variation IDs, actual exposure, purchase
   and next-renewal outcomes, joined to the prediction. Only observed,
   randomized outcomes can support a treatment-effect analysis.

Adapty's regular A/B tests split one placement/audience between published
flows or paywalls. An existing per-user CSV cannot directly create one. Its
profile custom attributes can drive segments, and its server-side API accepts
profile updates. The secret API key is for that server API; the authenticated
CLI manages test drafts. See the Adapty docs for [segments](https://adapty.io/docs/segments),
[profile updates](https://adapty.io/docs/api-adapty/operations/updateProfile),
and [CLI A/B tests](https://adapty.io/docs/developer-cli-ab-tests).

The current app has live Onboarding and Main flow tests. A new churn-targeted
test requires a reviewed segment, mapped identities, and published treatment
content. A strict per-user discount budget is not enforced by an ordinary
Adapty placement split; M5 must define a separate enforcement mechanism or
state the budget as a planning estimate.

## Grafana output

Add a provisioned **Churn Predictions** dashboard on the read-only PostgreSQL
datasource. Show prediction volume, risk distribution and age by app, model
version, horizon and `prediction_source`; count missing/invalid model outputs
as service errors rather than zero risk. Keep `mock` in a visibly separate
section. Do not expose user IDs. Once M5 event tables exist, show the number of
predicted, eligible, assigned, actually exposed and outcome-mature users by
experiment/arm, and model-version coverage. Calibration or treatment outcome
panels require real joined observations; absent events display no data. Never
label scenario break-even estimates as measured uplift or saved revenue.
