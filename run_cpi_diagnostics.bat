@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Run start_windows.bat first.
  pause
  exit /b 1
)
.venv\Scripts\python.exe research_cpi_diagnostics.py
if errorlevel 1 echo Diagnostics failed. Read the error above.
pause
