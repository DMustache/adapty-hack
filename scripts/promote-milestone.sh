#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEV="$ROOT/.worktrees/develop"
MS="${1:-}"
[[ "$MS" =~ ^M[0-9]+$ ]] || { echo "Usage: bash scripts/promote-milestone.sh M1" >&2; exit 2; }
[[ "$(git -C "$ROOT" branch --show-current)" == "main" ]] || { echo "Lead must run in main" >&2; exit 1; }
[[ -z "$(git -C "$ROOT" status --porcelain)" ]] || { echo "main dirty" >&2; exit 1; }
[[ -z "$(git -C "$DEV" status --porcelain)" ]] || { echo "develop dirty" >&2; exit 1; }
MARKER="$DEV/.agent-runtime/gates/$MS.ok"
[[ -f "$MARKER" ]] || { echo "No passing gate for $MS at develop commit" >&2; exit 1; }
PASSED="$(cat "$MARKER")"
CURRENT="$(git -C "$DEV" rev-parse HEAD)"
[[ "$PASSED" == "$CURRENT" ]] || { echo "STALE gate: tested=$PASSED current=$CURRENT. Rerun gate." >&2; exit 1; }
git -C "$ROOT" merge --no-ff --no-edit develop
echo "Promoted tested develop=$CURRENT to main. Lead can plan next milestone."
