@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Run start_windows.bat first to create the Python environment.
  pause
  exit /b 1
)
.venv\Scripts\python.exe hoplite_bridge.py import
set "RESULT=%ERRORLEVEL%"
if not "%RESULT%"=="0" echo Send the error above to ChatGPT.
pause
exit /b %RESULT%
