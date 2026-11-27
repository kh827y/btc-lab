@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Run start_windows.bat once first.
  pause
  exit /b 1
)
.venv\Scripts\python.exe binance_minute.py %*
if errorlevel 1 echo Archive has missing minutes or errors. See data\binance_1m\audit.json.
pause
