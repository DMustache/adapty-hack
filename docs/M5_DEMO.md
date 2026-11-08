# M5 demo: fixed churn model and simulated A/B events

The demo uses the unchanged `lumen-temporal-catboost` 1.0.0 artifact and synthetic Lumen subscriber histories. It demonstrates the workflow, not model accuracy on real customers or a measured discount effect.

1. Build cutoff-safe inputs for an active subscriber and score them with the pinned artifact. Show model ID, version, checksum, snapshot time and next renewal time.
2. Produce a retention experiment **proposal** for a reviewed risk cohort. Show control and treatment as proposed arms; do not claim an offer was delivered.
3. Replay deterministic, explicitly `simulated` assignment, exposure and next-renewal outcome fixtures through the same ingestion and join path intended for real events. No live Adapty placement, customer profile or payment is changed.
4. Show the linked prediction, test/variation, exposure and outcome in read-only views. Keep mock and simulated records visibly separate from real observations. Display counts and provenance; do not display inferred uplift, saved revenue, or a trained offer policy.

Acceptance: a fresh Compose run reproduces the scenario; retries do not duplicate events; a proposal without exposure cannot appear as an exposed user; a missing or immature outcome is shown as pending; every output retains source and UTC timestamps. The demo gate records the exact `develop` SHA. Real-client A/B learning and its success metric require a separate approved contract and are not claimed by this demo.
