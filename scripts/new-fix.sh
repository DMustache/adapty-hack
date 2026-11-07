#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[[ "$(git -C "$ROOT" branch --show-current)" == "main" ]] || { echo "Lead only, in main" >&2; exit 1; }
JOB="${1:-}"
MS="${2:-}"
ROLE="${3:-}"
[[ "$JOB" =~ ^FIX-[A-Z]+-[0-9]+$ && "$MS" =~ ^M[0-9]+$ ]] || { echo "Usage: bash scripts/new-fix.sh FIX-BE-001 M1 backend" >&2; exit 2; }
case "$ROLE" in backend|analytics|qa) ;; *) echo "Role must be backend|analytics|qa" >&2; exit 2;; esac
TARGET="$ROOT/.workflow/jobs/$JOB.md"
[[ ! -e "$TARGET" ]] || { echo "Job already exists" >&2; exit 1; }
sed -e "s/FIX-XXX/$JOB/g" -e "s/milestone: M1/milestone: $MS/" -e "s/role: backend/role: $ROLE/" "$ROOT/.workflow/templates/job.md" > "$TARGET"
echo "Created $TARGET. Edit acceptance and ownership, commit in main, sync-plan, spawn-job."
