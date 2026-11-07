---
id: FIX-BE-002
milestone: M2
role: backend
status: READY
depends_on: []
owned_paths:
  - services/inference/app/economics.py
  - services/inference/test_economics_m2.py
---
# FIX-BE-002: Preserve fractional unallocated budget

## Failing gate
`PATH=.worktrees/develop/.venv/bin:$PATH bash scripts/gate.sh M2` failed at `develop` SHA `a5d59534897f1d92f559eea241b6e11cb1360a4b`. Log: `.worktrees/develop/.agent-runtime/gates/M2.log`. Failing test: `tests/test_m2_economics_contract.py::test_zero_and_cent_level_budgets[0.009]`.

## Expected and actual
With a $0.009 budget and no affordable whole-cent discount, allocated exposure is $0 and `unallocated_budget_usd` should be $0.009, so allocated plus unallocated equals the stated budget. The current planner correctly allocates no offer but reports $0 unallocated because it exposes its floored spendable-cent counter.

## Work and ownership
Adjust only the owned economics source and its colocated regression test. Keep whole-cent spending conservative: floor the amount available for allocation and round each maximum face-value exposure up. Report unallocated budget as the original stated budget minus allocated exposure, retaining fractional cents. Preserve public schema, seeded assignments, mock/scenario labeling, and all other M2 invariants. Do not edit QA tests or contracts.

## Acceptance and handoff
The failing QA test passes; zero, fractional-cent, and ordinary budgets satisfy `allocated + unallocated = budget` within numeric tolerance while no allocation overspends. Run targeted backend and QA economics tests. Commit on `fix/FIX-BE-002`, write `handoffs/FIX-BE-002.md` with modified files, commands/results and blockers, and send Lead the commit SHA. Lead integrates and reruns the full M2 gate.
