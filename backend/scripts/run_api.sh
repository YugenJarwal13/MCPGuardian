#!/usr/bin/env bash
# Live-pipeline API (FastAPI + WebSocket) on http://127.0.0.1:8000.
# Run from anywhere: bash backend/scripts/run_api.sh   (it cds into backend/ itself)
# Also starts the ADK case manager as a real A2A server on a free local port.
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${PYTHON:-python}"
for cand in .venv/Scripts/python .venv/bin/python ../.venv/Scripts/python ../.venv/bin/python; do
  [ -x "$cand" ] && PY="$cand" && break
done
exec "$PY" -m uvicorn src.api.main:app --host 127.0.0.1 --port "${PORT:-8000}" "$@"
