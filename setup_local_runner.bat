@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Existing BTC-Lab Python environment required.
  pause
  exit /b 1
)
.venv\Scripts\python.exe -I -S -B local_runner.py setup
pause
