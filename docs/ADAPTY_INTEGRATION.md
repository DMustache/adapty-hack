# Adapty Integration Boundary (future work, outside hackathon demo)

This hackathon infrastructure **does not call undocumented Adapty write APIs** and never activates discounts automatically.

## Data -> decision

The offline seed repository supplies fictional Lumen users and transactions. The fixed external model produces a synthetic next-renewal risk score through the inference adapter; researcher-owned model work remains separate. The experiment planner takes risk, renewal price, and user ID and produces proposed `control`, `no_offer`, or `discount_XXpct` arms. The proposal is not an observed Adapty assignment.

## Decision -> Adapty experiment

1. Execute `POST /v1/retention/plan` to generate a **proposal** with budget cap and break-even hurdles.
2. Save the returned JSON plan (e.g. `plan.json`).
3. Run `python scripts/export_experiment_assignments.py plan.json proposed_arms.csv`.
4. Review offer eligibility, region, store products, trial status, pricing, and experiment design *manually*.
5. Outside the hackathon, a separately approved integration could map reviewed cohort and treatment definitions to verified Adapty segments/experiments; require explicit operator review before any live write. Adapty would own actual random assignment.
6. Later record randomized treatment assignments, exposures, and outcomes, with timestamps and purchase/revenue events. **Only then** could causal incremental revenue/uplift be evaluated.

The CSV is for **review/demo**, not proof of live Adapty compatibility. Control arm is retained, and `no_offer` users are not treated as a randomized holdout. Hypothetical discount economics must not be displayed as validated savings.
