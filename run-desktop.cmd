@echo off
setlocal
cd /d "%~dp0desktop"
if not exist "node_modules\.bin\electron.cmd" (
  echo Desktop dependencies are missing. Run build-desktop.cmd first.
  pause
  exit /b 1
)
call npm.cmd start
if errorlevel 1 pause
