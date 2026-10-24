#!/usr/bin/env bash
# Full evaluation (all ~1,762 cases) with a LOCAL Ollama model - meant for a machine with a GPU.
# No OpenRouter key and no .env are needed. Resumable: re-run the same command after any interruption.
#
#   cd backend
#   bash scripts/run_full_local_eval.sh                       # qwen3:4b, 4 parallel workers
#   MODEL=qwen3:14b WORKERS=2 bash scripts/run_full_local_eval.sh
#
# Prerequisites (once): Python 3.12 + `pip install -r requirements.txt` in an active venv, git, and Ollama
# installed. For parallel speed-up set OLLAMA_NUM_PARALLEL=4 for the Ollama *server* and restart it
# (PowerShell: setx OLLAMA_NUM_PARALLEL 4  -> quit and reopen Ollama).
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${PYTHON:-python}"
MODEL="${MODEL:-qwen3:4b}"
WORKERS="${WORKERS:-4}"
NAME="${NAME:-ollama_full}"

command -v ollama >/dev/null 2>&1 || { echo "ollama not found on PATH - install it from https://ollama.com"; exit 1; }
echo "[1/4] model: $MODEL"
ollama pull "$MODEL"

echo "[2/4] datasets (MCPTox + DVMCP clones into backend/external/)"
bash scripts/setup_mcptox.sh >/dev/null
bash scripts/setup_dvmcp.sh >/dev/null || true      # clones; falls back to the native launcher without Docker

echo "[3/4] starting the DVMCP lab (native, 127.0.0.1 only)"
"$PY" scripts/run_dvmcp_native.py > logs/dvmcp_lab.log 2>&1 &
LAB_PID=$!
trap 'kill $LAB_PID 2>/dev/null || true' EXIT
for _ in $(seq 1 60); do
  up=0; for p in $(seq 9001 9010); do (echo > /dev/tcp/127.0.0.1/$p) 2>/dev/null && up=$((up+1)); done
  [ "$up" -eq 10 ] && break; sleep 2
done
[ "$up" -eq 10 ] || { echo "DVMCP lab did not come up (see backend/logs/dvmcp_lab.log)"; exit 1; }

echo "[4/4] evaluating ALL cases with $MODEL ($WORKERS workers) -> reports/cases_$NAME.jsonl"
# keep the model resident on a big-RAM/GPU machine (the evaluator otherwise unloads it after every call)
export LLM_OLLAMA_KEEP_ALIVE="${LLM_OLLAMA_KEEP_ALIVE:-60m}"
export LLM_FALLBACK_MODEL="$MODEL"
PYTHONUNBUFFERED=1 "$PY" -m src.evaluation.run_eval --llm --full --provider ollama \
  --workers "$WORKERS" --name "$NAME"

echo
echo "Done. Send back this file:  backend/src/evaluation/reports/cases_$NAME.jsonl"
