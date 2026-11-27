@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Run start_windows.bat once first.
  pause
  exit /b 1
)
.venv\Scripts\python.exe research_cpi.py %*
if errorlevel 1 echo Preparation failed. Read the error above.
pause
