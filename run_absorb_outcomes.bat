@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Run start_windows.bat first.
  pause
  exit /b 1
)
if not exist data\research\absorb_v1\absorb_preflight.json (
  echo Preflight report not found. Run run_absorb_preflight.bat and have it reviewed first.
  pause
  exit /b 1
)
echo ABSORB-001 outcomes: ONE run only. It opens forward returns for 2018-2023.
echo Continue only after the preflight report has been reviewed.
set /p HASH=Paste the reviewed preflight SHA-256 (empty to cancel): 
if "%HASH%"=="" (
  echo Cancelled. Nothing was computed.
  pause
  exit /b 0
)
.venv\Scripts\python.exe research_absorb.py outcomes --preflight-sha256 %HASH%
if errorlevel 1 echo ABSORB-001 outcomes stopped. Send the message above.
pause
