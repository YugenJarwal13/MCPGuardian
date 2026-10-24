@echo off
rem Starts the API on http://127.0.0.1:8000 using the OpenRouter models from .env.
rem   start-backend.cmd         OpenRouter only (fast, recommended for demos)
rem   start-backend.cmd local   also allow the local Ollama model as a last-resort fallback (slow without a GPU)
setlocal
cd /d "%~dp0backend"
set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
set "LLM_PROVIDER=openrouter"
set "LLM_LOCAL_FALLBACK=off"
if /i "%~1"=="local" set "LLM_LOCAL_FALLBACK=on"
"%PY%" -m uvicorn src.api.main:app --host 127.0.0.1 --port 8000
