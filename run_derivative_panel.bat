@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Run start_windows.bat first.
  pause
  exit /b 1
)
echo Historical hourly panel. Internet required. No keys. Existing archives are reused.
echo Many daily OI archives must be downloaded. Do not start during journal issuance.
.venv\Scripts\python.exe research_derivative_panel.py
if errorlevel 1 echo Panel stopped. Send the error above.
pause
