@echo off
setlocal
cd /d "%~dp0"
python scripts\install.py %*
set "campus_result=%ERRORLEVEL%"
if not "%campus_result%"=="0" echo Installation did not complete. See the error above.
pause
exit /b %campus_result%
