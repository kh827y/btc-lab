@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Run start_windows.bat first.
  pause
  exit /b 1
)
.venv\Scripts\python.exe research_early_usd.py
if errorlevel 1 echo Early history audit stopped. Send error above.
pause
