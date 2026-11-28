@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Run start_windows.bat first.
  pause
  exit /b 1
)
.venv\Scripts\python.exe live_derivatives.py
if errorlevel 1 echo Send the error above to ChatGPT.
pause
