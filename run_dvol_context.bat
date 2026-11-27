@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Run start_windows.bat first.
  pause
  exit /b 1
)
.venv\Scripts\python.exe research_dvol_context.py
if errorlevel 1 echo DVOL unavailable. Send error above.
pause
