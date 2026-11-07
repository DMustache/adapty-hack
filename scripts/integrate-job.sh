#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEV="$ROOT/.worktrees/develop"
JOB="${1:-}"
[[ "$JOB" =~ ^(M[0-9]+|FIX)-[A-Z]+-[0-9]+$ ]] || { echo "Usage: bash scripts/integrate-job.sh M1-BE-001" >&2; exit 2; }
[[ "$(git -C "$ROOT" branch --show-current)" == "main" ]] || { echo "Lead must run from main" >&2; exit 1; }
BRANCH="task/$JOB"
if [[ "$JOB" == FIX-* ]]; then BRANCH="fix/$JOB"; fi
TREE="$ROOT/.worktrees/$JOB"
[[ -d "$TREE" ]] || { echo "No worktree for $JOB" >&2; exit 1; }
[[ -z "$(git -C "$TREE" status --porcelain)" ]] || { echo "Worker has uncommitted changes in $TREE" >&2; exit 1; }
[[ -z "$(git -C "$DEV" status --porcelain)" ]] || { echo "develop has uncommitted changes" >&2; exit 1; }
[[ "$(git -C "$DEV" branch --show-current)" == "develop" ]] || exit 1
if git -C "$DEV" merge-base --is-ancestor "$BRANCH" develop; then
  echo "Already integrated $BRANCH"
else
  git -C "$DEV" merge --no-ff --no-edit "$BRANCH"
fi
echo "Integrated $BRANCH -> develop at $(git -C "$DEV" rev-parse --short HEAD)"
echo "Do NOT promote yet. Integrate other milestone jobs, then run scripts/gate.sh <MILESTONE>."
