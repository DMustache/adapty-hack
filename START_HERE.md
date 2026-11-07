# Start Here — Smart Retention Offers

This repository is the infrastructure team's part of the hackathon. Churn modeling belongs to the separate ML researcher; your agents must not train, tune, or derive labels.

1. Review `README.md` and `docs/MODEL_HANDOFF.md` (give handoff to researcher).
2. Configure Git identity, then run `bash scripts/bootstrap.sh` in the extracted root.
3. Lead starts in `main` with `LEAD_START_PROMPT.md` and reads only active milestone/role instructions.
4. Commit new contracts/jobs on `main`; run `bash scripts/sync-plan.sh`.
5. Spawn worker worktrees, e.g. `bash scripts/spawn-job.sh M1-BE-001` and `bash scripts/spawn-job.sh M1-QA-001`.
6. Launch separate coding agents in each printed worktree directory; they read `.agent-runtime/ASSIGNMENT.md`.
7. Once committed: `scripts/integrate-job.sh` each job, then `scripts/gate.sh M1` on integrated `develop`.
8. On PASS: `scripts/promote-milestone.sh M1`. On FAIL: new FIX-job from Lead in `main`, re-sync, reassign, reintegrate, regate.

Quick demo independent of Git: `cp .env.example .env && docker compose up --build -d && python scripts/smoke_demo.py`.

Grafana dashboard: http://localhost:3000/d/smart-retention. The dashboard shows mock risk and *scenario* experiments, not measured savings.
