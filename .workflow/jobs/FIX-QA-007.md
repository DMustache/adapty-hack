---
id: FIX-QA-007
milestone: M5
role: qa
status: READY
depends_on: [M5-QA-003]
owned_paths: [scripts/]
---
# Correct offline checkpoint entrypoint from develop

Failing command: `bash scripts/offline_checkpoint.sh` from main at develop `1046ee9` returns no such file because the script has not been promoted. Running its develop copy currently resolves the wrong root. Update the script to locate the main project root when invoked from the develop worktree, while retaining exact-SHA and clean-develop checks. Acceptance: the checkpoint launches from main using the develop script path and records the tested SHA.
