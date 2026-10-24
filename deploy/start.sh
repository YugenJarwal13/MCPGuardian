#!/usr/bin/env bash
# Container entrypoint: start the DVMCP lab (127.0.0.1 only), wait for it, then serve the API + web app.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../backend"
mkdir -p logs

python scripts/run_dvmcp_native.py > logs/dvmcp_lab.log 2>&1 &

for _ in $(seq 1 60); do
  up=0
  for p in $(seq 9001 9010); do
    (echo > "/dev/tcp/127.0.0.1/$p") 2>/dev/null && up=$((up + 1))
  done
  [ "$up" -eq 10 ] && break
  sleep 2
done
echo "DVMCP lab: $up/10 servers up"

# --ws-max-size: requests are tiny JSON messages; anything larger is refused by the server itself.
exec python -m uvicorn src.api.main:app --host 0.0.0.0 --port "${PORT:-7860}" \
  --ws-max-size 65536 --proxy-headers --forwarded-allow-ips='*'
