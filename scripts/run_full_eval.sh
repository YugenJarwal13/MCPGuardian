#!/usr/bin/env bash
# Phase 8 / 11.5 — one-shot: ensure DVMCP is up, run the evaluation, tear down.
#   bash scripts/run_full_eval.sh          # deterministic baseline
#   bash scripts/run_full_eval.sh --llm    # LLM pipeline (needs provider creds in .env)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PY="${PYTHON:-python}"
[ -x .venv/Scripts/python ] && PY=.venv/Scripts/python
[ -x .venv/bin/python ] && PY=.venv/bin/python

port_up() { (echo > /dev/tcp/127.0.0.1/9001) 2>/dev/null; }

LAB_PID=""
if ! port_up; then
  echo "Starting DVMCP lab (native, 127.0.0.1 only)..."
  "$PY" scripts/run_dvmcp_native.py > logs/dvmcp_lab.log 2>&1 &
  LAB_PID=$!
  for _ in $(seq 1 30); do port_up && break; sleep 1; done
fi

echo "Running evaluation (all three ablation configs)..."
"$PY" -m src.evaluation.run_eval "$@"

if [ -n "$LAB_PID" ]; then
  echo "Stopping DVMCP lab..."
  kill "$LAB_PID" 2>/dev/null || true
fi

echo "Reports written to src/evaluation/reports/ and docs/evaluation_report.md"
