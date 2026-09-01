#!/usr/bin/env bash
# Phase 8 — one-shot: ensure DVMCP is up, run the full evaluation, tear down.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

STARTED_LAB=0
if ! docker ps --format '{{.Names}}' | grep -q '^dvmcp-lab$'; then
  echo "Starting DVMCP lab..."
  bash scripts/setup_dvmcp.sh
  STARTED_LAB=1
fi

echo "Running full evaluation (all three ablation configs)..."
python -m src.evaluation.run_eval

if [ "$STARTED_LAB" -eq 1 ]; then
  echo "Tearing down DVMCP lab..."
  docker rm -f dvmcp-lab >/dev/null 2>&1 || true
fi

echo "Reports written to src/evaluation/reports/ and docs/evaluation_report.md"
