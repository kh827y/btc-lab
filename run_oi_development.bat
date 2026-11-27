@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Run start_windows.bat first.
  pause
  exit /b 1
)
.venv\Scripts\python.exe research_oi.py
if errorlevel 1 echo OI failed. Send coverage.json or error above.
pause
