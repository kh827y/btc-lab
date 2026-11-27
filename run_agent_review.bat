@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Run start_windows.bat first.
  pause
  exit /b 1
)
.venv\Scripts\python.exe research_metadata.py --live-review --budget-units 200000
if errorlevel 1 echo Review stopped. Do not retry automatically. Send report or error.
pause
