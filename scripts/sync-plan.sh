#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEV="$ROOT/.worktrees/develop"
[[ "$(git -C "$ROOT" branch --show-current)" == "main" ]] || { echo "Lead must run from main" >&2; exit 1; }
[[ -d "$DEV" ]] || { echo "Run scripts/bootstrap.sh first" >&2; exit 1; }
[[ -z "$(git -C "$ROOT" status --porcelain)" ]] || { echo "Commit Lead plans/contracts in main before sync" >&2; exit 1; }
[[ -z "$(git -C "$DEV" status --porcelain)" ]] || { echo "develop has uncommitted files; clean up first" >&2; exit 1; }
[[ "$(git -C "$DEV" branch --show-current)" == "develop" ]] || { echo "Develop worktree on wrong branch" >&2; exit 1; }
git -C "$DEV" merge --no-ff --no-edit main
echo "Plan synced to develop at $(git -C "$DEV" rev-parse --short HEAD). Spawn jobs now."
