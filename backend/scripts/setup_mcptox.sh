#!/usr/bin/env bash
# Clone the MCPTox benchmark (attack-only dataset).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="$ROOT/external/MCPTox-Benchmark"

if [ ! -d "$DEST/.git" ]; then
  git clone https://github.com/zhiqiangwang4/MCPTox-Benchmark "$DEST"
else
  echo "MCPTox-Benchmark already cloned at $DEST"
fi

echo "Contents:"
ls -la "$DEST"
