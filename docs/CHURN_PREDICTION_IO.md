# Churn predictor I/O and Adapty A/B handoff

## M5 frozen interface (schema version 1.0)

`contracts/schemas/temporal-churn-request.schema.json` is the model-specific
validation layer over the unchanged v1 request. The temporal fields live in
`context`: `as_of_at` is the UTC decision and feature cutoff; `renewal_due_at`
is the known end of the current paid period and must be later than `as_of_at`;
`renewal_horizon_days` is `ceil((renewal_due_at - as_of_at) / 86400 seconds)`
and must be 1–365. `features.renewal_price_usd` is the positive USD price of
the **current paid receipt**, used as an estimate for the next renewal; it is
not a verified future offer price. `features.days_until_renewal` retains the
unrounded duration in days. Temporal validation enforces these cross-field
relationships after JSON Schema validation. Other v1 model requests continue
to use the existing schema.

The fixed model target is failure to renew at the next eligible renewal for
any reason, including billing failure and refund. Its output is a synthetic
holdout risk estimate for that target. Calibration metrics in the imported
report are evidence only for that synthetic distribution; do not imply live
calibration. The artifact ID/version/checksum and all 23 required feature
types and null allowances are copied from
`services/inference/models/temporal_catboost/metadata.json` at
`origin/temporal-churn` commit `7dc9a9692798111e9ec4fb8af3d8a97aee8dae66`.
The committed example retains the research fixture values. A field allowed
to be `null` by the artifact is still required as a key; a missing source is
not permission to invent a non-null value or score operational traffic.

### Feature source and cutoff audit

The only available raw files are the local synthetic `users.csv.gz` and
`transactions.csv.gz`. `users.user_id` joins to `transactions.user_id` inside
the offline source; operational IDs must be pseudonymous and mapped separately
to a verified Adapty profile/customer ID. Use event time **and** source
availability time at or before `as_of_at`; the offline files have no ingestion
time, so they do not establish operational availability.

| Feature keys | Offline values and cutoff construction | Operational status |
|---|---|---|
| `plan`, `renewal_price_usd`, `started_with_trial` | Paid weekly/monthly transaction receipt, and earlier trial receipt | Receipt history required |
| `platform`, `country`, `acquisition_channel`, `onboarding_goal`, `push_opt_in`, `app_version`, `placement`, `flow`, `ai_edits_first_day`, `photos_imported` | `users.csv.gz`; no field-level change or observation timestamps | Unproven at snapshot cutoff; require dated source before operational scoring |
| `price_index` | Imported loader computes country annual-price median from the entire transaction file | Future-receipt leakage in offline construction; synthetic replay only until cutoff-safe source and ML compatibility are reviewed |
| `tenure_days`, `renewal_count`, `days_until_renewal`, `days_since_last_payment`, `historical_renewal_success_rate` | Paid receipt chain through cutoff, known current `expires_at`; success rate is null before first completed renewal | Receipt/renewal history required; no outcome event after cutoff may enter |
| `billing_issues_last_30d` | Count detected timestamps in `(as_of_at - 30 days, as_of_at]` | Dated billing-issue source required |
| `days_since_install` | `users.install_at` through cutoff | Dated install source required |
| `auto_renew_off`, `days_since_auto_renew_off` | Latest status-change event known at cutoff; days value null when off is false | Dated status history required |

The source table is exhaustive for the 23 deployed keys. The imported snapshot
replay accepts a paid, entitled weekly/monthly subscriber, excludes a refund
already observed, and uses the current period's `expires_at` as the next due
time. It labels an outcome only when the due time is at least one day before
the observation cutoff. Synthetic fixture scoring may reproduce the imported
values, including the documented source limitations. The operational builder
must return an unscored missing-source state when a value or its cutoff safety
cannot be established. It must not substitute later receipts, global medians,
or current profile values for earlier facts.

### Versioned lifecycle records

The schemas and examples in `contracts/` define immutable model metadata,
approved cohort/policy, profile sync, draft test, assignment, exposure, and
next-renewal outcome records. Join by `(app_id, user_id, prediction_id,
model_id, model_version)` and the frozen renewal due time; join test events by
`(experiment_id, variation_id)` and source event ID. Each record has a UTC
event time, ingest time, source, and idempotency key. A repeated key with a
different payload is a conflict; missing assignment, exposure, or mature
outcome remains absent, never inferred from a proposal or transaction alone.

Freeze a cohort ID, policy version, selected prediction IDs, and membership
cutoff before profile writes. The identity map from our pseudonymous ID to a
verified Adapty profile/customer ID is restricted service-side data, not a
Grafana dimension or export. A sync acknowledgment is not proof that a segment
has propagated: a draft requires a verified segment and a recorded readiness
check after propagation. An unset attribute means unknown, not low risk.
The draft maps reviewed control/treatment content and actual store offers to
Adapty variation IDs. Adapty randomizes actual arms; planner assignments are
scenario proposals only. `budget_usd` and exposure are estimates: a regular
placement A/B split does not enforce a strict per-user discount cap.

The offline `users.ab_test` value identifies no assignment or view event.
Neither CSV has a test/variation assignment, paywall exposure, or verified
next-renewal outcome linkage. The deterministic M5 event examples are therefore
marked `simulated`; they demonstrate ingestion and joins, not observed effect.
No customer test data is expected for this demo. Real-event dashboards and
audit exports remain empty in M5. The simulated events are not training or
validation data for the fixed churn model. No live placement activation occurs
in M5.

Source audit evidence (local, ignored files; do not commit their rows):
`users.csv.gz` has 50,000 rows, SHA256
`5fd57c54395ff1ee885acf57704b142faada43ab15403be7070cbc5b98c6954b`;
its only test-related column is `ab_test`. `transactions.csv.gz` has 29,794
rows, SHA256
`9ea75794c827de67c23fc67f21a959a02d18603bc27fb325560e5c662d759193`;
it has no assignment, variation, exposure, view, or experiment column.
Transactions contain purchases, expiry, billing issue and refund timestamps;
they do not establish which randomized content a subscriber actually saw.

The ML review basis for this freeze is the immutable artifact metadata,
evaluation report and deterministic fixture at `origin/temporal-churn`
`7dc9a9692798111e9ec4fb8af3d8a97aee8dae66`, as accepted for M5 planning.
This records the target and synthetic holdout metrics; it is not a new
operational calibration approval. The integration surface review below freezes
the interface; a named integration owner must still approve real tenant IDs,
treatment content and any profile write before an Adapty draft is created.

### Integration surface review, 2026-11-08 UTC

Read-only Adapty CLI inspection of Lumen app
`2112a0d1-4aca-4cf3-8113-e70272b9aaef` found five flow placements,
seven published flows, three segments, two live flow tests and one draft.
There is no churn cohort segment. Main and Onboarding already have live tests;
the Main placement's North American audience currently serves one. No
published flow or store offer was verified as the proposed retention
treatment. These are concrete `not_ready` conditions for a churn draft on
those resources, not reasons to infer an assignment or change a live test.

The documented profile update is `PATCH /api/v2/server-side-api/profile/`:
identify a verified profile with exactly one of `adapty-profile-id` or
`adapty-customer-user-id` headers; encode the typed value in
`custom_attributes: [{"key": "churn_cohort", "value": "<cohort-id>"}]`.
The internal profile-sync record is an audit record, not that HTTP body.
The custom key and type must first exist in the dashboard; a String attribute
uses predefined values, and each profile may have at most 30 custom
attributes. Treat an API 200 as acknowledgment, then verify segment membership
separately because profile/segment updates can lag. Missing attributes do not
match a typed comparison and cannot mean low risk.

The documented CLI creates a **draft** test from published flows on a flow
placement, with an optional planned segment; it does not affect users until
started. `start` is outside M5. For flow tests, the canonical
`variation_id` in our records maps to Adapty `ab_test_variant_id` (which
matches `flow_variation_id`), **not** the webhook's `variation_id` for a paywall
screen. Subscription webhooks can carry the test and variant of an attributed
purchase or renewal, but they are not proof that every eligible user was
assigned or actually viewed a flow. Assignment and exposure need separately
verified SDK/event-level capture; absent records stay absent. Deduplicate
webhooks using `profile_event_id` or transaction IDs and preserve receipt time
because event times may arrive out of order. An observed nonrenewal requires a
complete event source through the outcome maturity cutoff, not merely the
absence of a purchase row.

This review verifies the documented integration shape and current read-only
tenant state. It does not approve a real customer test, profile write, or
specific treatment content. No Grafana action is needed to validate these
Adapty facts: local Grafana is a read-only PostgreSQL consumer and the Compose
stack was not running during this review.

This is the target integration for the external churn predictor. The application
services do not train or update model weights. `origin/model-implementation`
contains `discount_advisor/`, a synthetic-data cohort experiment advisor, not
a churn predictor. `origin/temporal-churn` at
`7dc9a9692798111e9ec4fb8af3d8a97aee8dae66` contains the CatBoost
predictor, a checksummed artifact, adapter, fixture and evaluation report.
The deployable `lumen-temporal-catboost` 1.0.0 artifact was introduced by
`7475a89`; the later history-feature ablation did not change it. Treat this
artifact unchanged; M5-ML-001 verifies whether this exact version can be used.

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

For the fixed temporal model, the 23 deployed feature keys, types and null policy
are in `services/inference/models/temporal_catboost/metadata.json` on that
branch. Its target is failure to renew at the next eligible renewal for any
reason, including billing failure and refund. The ML owner must confirm this
target and reported calibration before activation, without changing the model. A temporal request also supplies
UTC `as_of_at`, `renewal_due_at` and positive `renewal_price_usd`;
`renewal_horizon_days` describes the same next renewal, not a separate
fixed-window target. Preserve existing v1 requests for other models. Do not
copy `discount_advisor` aggregates into these features. The trusted `ModelAdapter` loads the
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
All timestamps are UTC. The fixed model supplies a CatBoost `.cbm` artifact with
SHA256 `4f3fd0acc9944b19fd0743d3c0b8a8863b8d59e1e81065c5a0940d5b9fad1491`,
metadata, evaluation report and deterministic fixture. M5-ML-001 must confirm
runtime, target and calibration. The service pins this exact artifact and
refuses a changed checksum; no candidate switching or weight updates are in scope. Its offline replay script demonstrates
synthetic snapshots; M5-BE-004 owns a cutoff-safe request builder from approved
event sources for the running service.

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
   explicit mapping from our pseudonymous `user_id` to a verified Adapty
   profile ID or identified customer user ID. Pin the cohort's model and
   policy versions for the test.
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
