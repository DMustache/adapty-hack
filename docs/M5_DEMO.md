# M5 demo: fixed churn model and simulated A/B events

The demo uses the unchanged `lumen-temporal-catboost` 1.0.0 artifact and synthetic Lumen subscriber histories. It demonstrates the workflow, not model accuracy on real customers or a measured discount effect.

No new customer or live A/B test data will arrive for this demo. The churn
model is already trained and frozen; its fixture, metadata and synthetic
subscriber snapshots are sufficient to test model loading, input validation,
cutoff behavior and scoring. **A/B simulation is not model test data and must
never train, tune, recalibrate or validate the churn model.** Simulated A/B
events are needed only for the separate experiment-lineage and illustrative
offer-policy demo. Without that demo step, no A/B simulation is needed.

1. Build cutoff-safe inputs for an active subscriber and score them with the pinned artifact. Show model ID, version, checksum, snapshot time and next renewal time.
2. Produce a retention experiment **proposal** for a synthetic risk cohort marked approved in the demo fixture. Show control and treatment as proposed arms; do not claim a real operator reviewed the cohort or that an offer was delivered.
3. Replay deterministic, explicitly `simulated` assignment, exposure and next-renewal outcome fixtures through the same ingestion and join path intended for real events. No live Adapty placement, customer profile or payment is changed.
4. Run an isolated illustrative offer-policy review on the simulated, outcome-mature records only. It records a new **demo offer-policy version in the local output JSON**, leaves the churn artifact unchanged, and returns `manual_review_required`. This is not a persisted production policy or a learning algorithm.
5. Show prediction, test/variation, exposure and outcome lineage in Grafana's read-only views; show the demo policy version in the output JSON. Keep mock and simulated records visibly separate from real observations. Display counts and provenance; do not report discount uplift, saved revenue or real-client accuracy.

Acceptance: a fresh Compose run reproduces the scenario; retries do not duplicate events; a proposal without exposure cannot appear as an exposed user; a missing or immature outcome is shown as pending and excluded from the learning example; every output retains source and UTC timestamps. The churn model checksum is identical before and after the learning step. The demo gate records the exact `develop` SHA. Real-client A/B learning, its production algorithm and success metric require a separate approved contract and are not claimed by this demo.
