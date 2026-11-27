@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Run start_windows.bat first.
  pause
  exit /b 1
)
.venv\Scripts\python.exe research_daily_usd.py
if errorlevel 1 echo Daily history failed. Read the error above. Cached responses retained.
pause
