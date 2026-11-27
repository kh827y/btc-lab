@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Run start_windows.bat first.
  pause
  exit /b 1
)
.venv\Scripts\python.exe risk_journal.py issue
if errorlevel 1 (
  echo Risk journal issue failed. Send error above.
  pause
  exit /b 1
)
echo Independent OI availability check. Risk forecast already saved.
.venv\Scripts\python.exe research_oi_readiness.py
if errorlevel 1 echo OI source check failed. Risk forecast remains saved; send it on time.
echo Offline weekly decision sheet.
.venv\Scripts\python.exe research_decision_sheet.py
if errorlevel 1 echo Decision sheet unavailable. Risk forecast remains saved.
pause
