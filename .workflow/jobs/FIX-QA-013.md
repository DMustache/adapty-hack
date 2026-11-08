---
id: FIX-QA-013
milestone: M8
role: qa
priority: P1
status: DONE
depends_on: [M8-QA-001]
owned_paths:
  - scripts/m8_live_demo.py
---
# Keep simulated variation IDs faithful to the planner

Failure: M8 gate at `c80e629` passed mechanically, but its `PLAN` output contained `no_offer: 1` for a 20% discount while the live demo mapped every non-control arm to `treatment`. Expected: all three demo assignments map only from actual `control` or `discount_5pct` planner arms, never a `no_offer` to a treatment variation. Use a feasible 5% hypothesis for these fixed synthetic fixture risks, assert the arm set before writing lineage, and retain 3/2/1 simulated event counts. Parent M8; rerun the exact-SHA gate.
