@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Run start_windows.bat first.
  pause
  exit /b 1
)
.venv\Scripts\python.exe research_provider.py --live-smoke --budget-units 200000
if errorlevel 1 echo Pilot stopped. Do not retry automatically. Send the report or console error.
pause
