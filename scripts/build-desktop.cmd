@echo off
setlocal
cd /d "%~dp0.."
python scripts\build_desktop.py %*
set "campus_result=%ERRORLEVEL%"
if "%campus_result%"=="0" (echo Desktop build completed. Open the release folder.) else (echo Build stopped. See the error above.)
pause
exit /b %campus_result%
