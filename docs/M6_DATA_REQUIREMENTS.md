# M6 demo data and future integration requirements

The hackathon demo uses the unchanged `lumen-temporal-catboost` 1.0.0 artifact, the local synthetic Lumen seed archives and explicitly simulated experiment events. It does not score customers or write to Adapty. The reviewed local archives contain 50,000 user rows and 29,794 transaction rows; see `docs/CHURN_PREDICTION_IO.md` for their hashes and the frozen model interface.

| Need | Present in seed archives | What a future real integration would need |
| --- | --- | --- |
| Subscriber profile and product history | `users.csv.gz` has profile fields and install time; `transactions.csv.gz` has purchases, product, price, expiry, renewal status, billing issue and refund times. | Confirm which Adapty exports or app events provide each field with a stable pseudonymous join key. |
| Feature values as known at decision time | Transaction events have relevant timestamps. Most user profile values have no field-level observation or change time. The offline `price_index` is computed from the full transaction archive. | Dated profile/usage history and a cutoff-safe price reference, or an explicit missing-source result. Current values and future receipts cannot reconstruct an earlier decision. |
| Actual experiment assignment and exposure | `users.ab_test` is a profile label only. Neither CSV contains a verified variation assignment or offer/paywall exposure event. | Event ID, app/profile key, test and variation IDs, UTC assignment and exposure times, and source/ingest provenance from the Adapty/app integration. |
| Next-renewal outcome linked to exposure | Transactions contain purchase, expiry, billing and refund times, but no assignment/exposure linkage. | A mature renewal outcome keyed to the same subscriber, test/variation and renewal horizon, including the observation cutoff. |
| Consent and authorized use | The seed archives are fictional, synthetic data. | A separate policy and permission for any real customer data or live experiment; not part of this demo. |

For M6, show these missing links with deterministic simulated events. Do not interpret the `ab_test` label as randomization, a transaction as proof of exposure, or the simulated rows as measured discount uplift. The requested Adapty event/export fields are a future data contract, not a claim that the current seed files or tenant already provide them.
