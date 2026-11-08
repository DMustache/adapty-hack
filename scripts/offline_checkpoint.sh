#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEV="$ROOT/.worktrees/develop"
[[ "$(git -C "$ROOT" branch --show-current)" == main ]] || exit 1
[[ "$(git -C "$DEV" branch --show-current)" == develop ]] || exit 1
[[ -z "$(git -C "$DEV" status --porcelain)" ]] || exit 1
SHA="$(git -C "$DEV" rev-parse HEAD)"
export OFFLINE_DATA_DIR="${OFFLINE_DATA_DIR:-$ROOT/data}"
[[ -f "$OFFLINE_DATA_DIR/users.csv.gz" && -f "$OFFLINE_DATA_DIR/transactions.csv.gz" ]] || {
  echo "Offline source archives missing: $OFFLINE_DATA_DIR" >&2; exit 1;
}
mkdir -p "$DEV/.agent-runtime/gates"
REPORT="$DEV/.agent-runtime/gates/M5-offline-$SHA.log"
(
  cd "$DEV"
  echo "OFFLINE CHECKPOINT develop=$SHA source=$OFFLINE_DATA_DIR"
  python -m pytest -q
  docker compose config --quiet
  docker compose up --build -d
  docker compose exec -T analytics python -m services.analytics.import_offline
  docker compose exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SELECT (SELECT COUNT(*) FROM offline_users), (SELECT COUNT(*) FROM offline_transactions), (SELECT COUNT(*) FROM offline_imports)"' | grep -x '50000|29794|2'
  python scripts/smoke_demo.py
  echo "OFFLINE CHECKPOINT PASS $SHA"
) 2>&1 | tee "$REPORT"
echo "Log: $REPORT"
