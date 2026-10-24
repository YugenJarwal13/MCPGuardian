@echo off
rem Starts the DVMCP lab (ten deliberately vulnerable MCP servers) on 127.0.0.1:9001-9010.
setlocal
cd /d "%~dp0backend"
set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" scripts\run_dvmcp_native.py
