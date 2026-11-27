@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Run start_windows.bat first.
  pause
  exit /b 1
)
.venv\Scripts\python.exe research_buy_audit.py
if errorlevel 1 echo Audit controls failed. Read the error above.
pause
