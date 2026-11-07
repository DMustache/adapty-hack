# Lead-created task files

Every worker reads one job (`M#-ROLE-###.md` or `FIX-ROLE-###.md`) after role-scoped AGENTS. Lead freezes contracts on main, commits them, syncs to develop, then invokes `scripts/spawn-job.sh` per READY job. Feature branches start from develop; QA jobs may run concurrently. Workers commit to their own worktrees and report SHA; Lead integrates into develop, runs `gate.sh`, then promotes or writes FIX job. No worker rewrites task/contract specs.
