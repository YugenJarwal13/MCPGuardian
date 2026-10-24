@echo off
rem Starts the web app on http://localhost:5173 (it talks to the API on port 8000).
setlocal
cd /d "%~dp0frontend"
if not exist node_modules call npm install
call npm run dev
