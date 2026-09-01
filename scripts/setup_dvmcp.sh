#!/usr/bin/env bash
# Phase 1.1 — clone, build, and run the DVMCP challenge lab.
# Requires Docker (Linux containers). Idempotent-ish: re-running rebuilds.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="$ROOT/external/damn-vulnerable-MCP-server"

if [ ! -d "$DEST/.git" ]; then
  git clone https://github.com/harishsg993010/damn-vulnerable-MCP-server "$DEST"
fi

cd "$DEST"
docker build -t dvmcp .
# Remove any prior container of the same name before starting fresh.
docker rm -f dvmcp-lab >/dev/null 2>&1 || true
docker run -d -p 9001-9010:9001-9010 --name dvmcp-lab dvmcp

echo "Waiting for DVMCP challenge ports to come up..."
sleep 3
for p in $(seq 9001 9010); do
  curl -sf "localhost:$p" >/dev/null 2>&1 && echo "port $p OK" || echo "port $p not responding"
done
