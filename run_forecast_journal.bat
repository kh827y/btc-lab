@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Run start_windows.bat first.
  pause
  exit /b 1
)
.venv\Scripts\python.exe forecast_journal.py settle
if errorlevel 1 echo Settlement failed; existing records are retained.
.venv\Scripts\python.exe forecast_journal.py issue
if errorlevel 1 echo Forecast failed. Read the error above.
pause
