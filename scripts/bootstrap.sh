#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
if [[ -z "$(git config user.name || true)" || -z "$(git config user.email || true)" ]]; then
  echo "Configure Git first: git config --global user.name NAME; git config --global user.email EMAIL" >&2
  exit 1
fi
if [[ "$(git rev-parse --show-toplevel 2>/dev/null || true)" != "$ROOT" ]]; then
  git init -b main
fi
if ! git rev-parse --verify HEAD >/dev/null 2>&1; then
  git add .
  git commit -m "chore: initialize agent workspace and mock infrastructure"
fi
[[ "$(git branch --show-current)" == "main" ]] || { echo "Run bootstrap in the main worktree" >&2; exit 1; }
if ! git show-ref --verify --quiet refs/heads/develop; then
  git branch develop main
fi
DEV="$ROOT/.worktrees/develop"
mkdir -p "$ROOT/.worktrees"
if [[ ! -e "$DEV/.git" ]]; then
  git worktree add "$DEV" develop
fi
if [[ ! -f "$DEV/.env" ]]; then
  if [[ -f "$ROOT/.env" ]]; then cp "$ROOT/.env" "$DEV/.env"; else cp "$DEV/.env.example" "$DEV/.env"; fi
fi
printf '\nREADY\n main:    %s\n develop: %s\n\n' "$ROOT" "$DEV"
echo "Next: bash scripts/sync-plan.sh; bash scripts/spawn-job.sh M1-BE-001"
