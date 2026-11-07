# Lead-created task files

Every worker reads one job (`M#-ROLE-###.md` or `FIX-ROLE-###.md`) after role-scoped AGENTS. Lead freezes contracts on main, commits them, syncs to develop, then invokes `scripts/spawn-job.sh` per READY job. Feature branches start from develop; QA jobs may run concurrently. Workers commit to their own worktrees and report SHA; Lead integrates into develop, runs `gate.sh`, then promotes or writes FIX job. No worker rewrites task/contract specs.

`role: lead` and `role: external_ml` are tracker-only dependencies. Lead handles its own contract job on `main`; the separate ML owner handles model training and weights outside this repository. Neither role is dispatched with `scripts/spawn-job.sh`. Jobs marked BLOCKED are not spawned until their named dependencies are satisfied and Lead marks them READY in a planning sync.
