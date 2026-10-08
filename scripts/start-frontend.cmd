@echo off
setlocal
cd /d "%~dp0..\frontend"
if not exist "dist\index.html" (
  echo Run install.cmd first to compile the frontend.
  pause
  exit /b 1
)
call npm.cmd run preview
if errorlevel 1 pause
