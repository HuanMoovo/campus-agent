@echo off
setlocal
cd /d "%~dp0backend"
if not exist ".venv\Scripts\python.exe" (
  echo Run install.cmd first.
  pause
  exit /b 1
)
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
if errorlevel 1 pause
