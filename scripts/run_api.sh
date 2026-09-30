#!/usr/bin/env bash
# Live-pipeline API (FastAPI + WebSocket) on http://127.0.0.1:8000.
# Also starts the ADK case manager as a real A2A server on a free local port.
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${PYTHON:-python}"
[ -x .venv/Scripts/python ] && PY=.venv/Scripts/python
[ -x .venv/bin/python ] && PY=.venv/bin/python
exec "$PY" -m uvicorn src.api.main:app --host 127.0.0.1 --port "${PORT:-8000}" "$@"
