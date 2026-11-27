@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Run start_windows.bat first.
  pause
  exit /b 1
)
.venv\Scripts\python.exe research_protocol_design.py --live-design
if errorlevel 1 echo Pilot stopped. Do not retry. Send report or error.
pause
