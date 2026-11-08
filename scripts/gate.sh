#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEV="$ROOT/.worktrees/develop"
MS="${1:-}"
[[ "$MS" =~ ^M[0-9]+$ ]] || { echo "Usage: bash scripts/gate.sh M1" >&2; exit 2; }
[[ "$(git -C "$ROOT" branch --show-current)" == "main" ]] || { echo "Lead must run from main" >&2; exit 1; }
[[ "$(git -C "$DEV" branch --show-current)" == "develop" ]] || exit 1
[[ -z "$(git -C "$DEV" status --porcelain)" ]] || { echo "develop dirty: gate requires committed snapshot" >&2; exit 1; }
SHA="$(git -C "$DEV" rev-parse HEAD)"
if [[ -x "$DEV/.venv/bin/python" ]]; then
  PYTHON="$DEV/.venv/bin/python"
else
  PYTHON=python
fi
REPORTDIR="$DEV/.agent-runtime/gates"
mkdir -p "$REPORTDIR"
rm -f "$REPORTDIR/$MS.ok"
REPORT="$REPORTDIR/$MS.log"
(
  set -euo pipefail
  cd "$DEV"
  echo "GATE milestone=$MS commit=$SHA"
  echo "--- pytest ---"
  "$PYTHON" -m pytest -q
  echo "--- docker compose config ---"
  docker compose config --quiet
  echo "--- docker compose up ---"
  docker compose up --build -d
  echo "--- end-to-end smoke ---"
  "$PYTHON" scripts/smoke_demo.py
  if [[ "$MS" =~ ^M([3-9]|[1-9][0-9]+)$ ]]; then
    echo "--- live M3 analytics and Grafana QA ---"
    M3_QA_INTEGRATION=1 "$PYTHON" -m pytest -q tests/test_m3_analytics_contract.py -k postgres_ingestion
  fi
  if [[ "$MS" == M5 || "$MS" == M6 ]]; then
    echo "--- live M5 fixed-model and migration QA ---"
    M5_QA_INTEGRATION=1 "$PYTHON" -m pytest -q tests/test_m5_temporal_live.py
    echo "--- synthetic M5 experiment and policy demo ---"
    "$PYTHON" scripts/m5_demo.py --output "$REPORTDIR/m5-demo.json"
    echo "--- cutoff-safe synthetic audit export ---"
    "$PYTHON" scripts/export_m5_audit.py --demo-output "$REPORTDIR/m5-demo.json" \
      --output "$REPORTDIR/m5-audit.json"
  fi
  if [[ "$MS" == M6 ]]; then
    echo "--- three simulated M6 test outcomes and five Grafana dashboards ---"
    "$PYTHON" scripts/m6_multi_demo.py --output "$REPORTDIR/m6-multi-demo.json"
  fi
  echo "GATE PASS $MS $SHA"
) 2>&1 | tee "$REPORT"
# With pipefail, failures above stop this script before the marker is written.
printf '%s\n' "$SHA" > "$REPORTDIR/$MS.ok"
echo "PASS marker: $REPORTDIR/$MS.ok"
