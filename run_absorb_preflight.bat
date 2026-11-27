@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Run start_windows.bat first.
  pause
  exit /b 1
)
if not exist data\binance_1m\audit.json (
  echo Minute archive not found. Run download_minutes.bat first.
  pause
  exit /b 1
)
echo ABSORB-001 preflight: validity and sample adequacy. No forward outcomes are computed.
echo Reading the local minute archive up to 2023-12-31 takes several minutes.
.venv\Scripts\python.exe research_absorb.py preflight
if errorlevel 1 echo ABSORB-001 preflight stopped. Send the message above.
pause
