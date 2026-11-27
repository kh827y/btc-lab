@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Run start_windows.bat first.
  pause
  exit /b 1
)
.venv\Scripts\python.exe research_oi_gate.py
if errorlevel 1 echo Synthetic gate stopped. Send error and any oracle_preflight.json. Do not rerun blindly.
pause
