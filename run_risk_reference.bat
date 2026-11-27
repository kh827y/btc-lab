@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Run start_windows.bat first.
  pause
  exit /b 1
)
.venv\Scripts\python.exe research_risk_reference.py
if errorlevel 1 echo RISK failed. Send error above.
pause
