#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEV="$ROOT/.worktrees/develop"
JOB="${1:-}"
[[ "$JOB" =~ ^(M[0-9]+|FIX)-[A-Z]+-[0-9]+$ ]] || { echo "Usage: bash scripts/spawn-job.sh M1-BE-001 (or FIX-BE-001)" >&2; exit 2; }
[[ "$(git -C "$ROOT" branch --show-current)" == "main" ]] || { echo "Lead must run from main" >&2; exit 1; }
[[ -d "$DEV" ]] || { echo "Run bootstrap first" >&2; exit 1; }
JOBFILE="$DEV/.workflow/jobs/$JOB.md"
[[ -f "$JOBFILE" ]] || { echo "Job absent in develop; commit job on main and run sync-plan.sh" >&2; exit 1; }
git -C "$DEV" ls-files --error-unmatch ".workflow/jobs/$JOB.md" >/dev/null || {
  echo "Job file is not committed in develop" >&2; exit 1;
}
ROLE="$(sed -n 's/^role: //p' "$JOBFILE" | head -n 1)"
STATUS="$(sed -n 's/^status: //p' "$JOBFILE" | head -n 1)"
case "$ROLE" in backend|analytics|qa) ;; *) echo "Unknown worker role: $ROLE" >&2; exit 1;; esac
[[ "$STATUS" == READY ]] || { echo "Job must be READY (got $STATUS)" >&2; exit 1; }
BRANCH="task/$JOB"
if [[ "$JOB" == FIX-* ]]; then BRANCH="fix/$JOB"; fi
TREE="$ROOT/.worktrees/$JOB"
[[ ! -e "$TREE" ]] || { echo "Worktree already exists: $TREE" >&2; exit 1; }
[[ -z "$(git -C "$DEV" status --porcelain)" ]] || { echo "develop is dirty; do not fork" >&2; exit 1; }
git -C "$ROOT" worktree add -b "$BRANCH" "$TREE" develop
mkdir -p "$TREE/.agent-runtime"
cat > "$TREE/.agent-runtime/ASSIGNMENT.md" <<ASSIGNMENT
# Worker assignment: $JOB

Role: **$ROLE**
Branch: \`$BRANCH\`
Working tree: \`$TREE\`

Read in this order:
1. \`AGENTS.md\` (short routing file)
2. Your scoped AGENTS.md:
   - backend: \`services/inference/AGENTS.md\`
   - analytics: \`services/analytics/AGENTS.md\`
   - qa: \`tests/AGENTS.md\`
3. \`.workflow/jobs/$JOB.md\`
4. Referenced \`contracts/schemas/*\` only when necessary.

Do not work outside owned paths. Commit your changes to \`$BRANCH\`.
Send Lead the commit SHA and handoff when finished. No direct merge to develop.
ASSIGNMENT
printf 'READY: %s\nRead: %s/.agent-runtime/ASSIGNMENT.md\n' "$TREE" "$TREE"
