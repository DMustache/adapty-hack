# Adapty Integration Boundary (planned, not active)

This hackathon infrastructure **does not call undocumented Adapty write APIs** and never activates discounts automatically.

## Data -> decision

The offline seed repository supplies fictional Lumen users and transactions. Researcher owns leakage-safe churn label construction and churn-model output. The inference adapter receives a `churn_probability` for an *active weekly/monthly subscriber* and returns a labeled model prediction. Experiment planner takes risk, renewal price, and user ID, produces randomized `control`, `no_offer`, or `discount_XXpct` assignments.

## Decision -> Adapty experiment

1. Execute `POST /v1/retention/plan` to generate a **proposal** with budget cap and break-even hurdles.
2. Save the returned JSON plan (e.g. `plan.json`).
3. Run `python scripts/export_experiment_assignments.py plan.json proposed_arms.csv`.
4. Review offer eligibility, region, store products, trial status, pricing, and experiment design *manually*.
5. When a **documented and authorized** Adapty integration path is confirmed, implement a separate adapter in the existing service to map proposal arm identifiers to Adapty segments/experiments; require explicit operator review before writing live offers.
6. Later record randomized treatment assignments, exposures, and outcomes, with timestamps and purchase/revenue events. **Only then** could causal incremental revenue/uplift be evaluated.

The CSV is for **review/demo**, not proof of live Adapty compatibility. Control arm is retained, and `no_offer` users are not treated as a randomized holdout. Hypothetical discount economics must not be displayed as validated savings.
