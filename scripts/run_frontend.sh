#!/usr/bin/env bash
# React UI (Vite dev server) on http://localhost:5173, proxying the API on :8000.
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/frontend"
[ -d node_modules ] || npm install
exec npm run dev -- --host 127.0.0.1 "$@"
