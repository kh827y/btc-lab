@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Run start_windows.bat first.
  pause
  exit /b 1
)
echo Source audit only. Internet required, no keys.
echo Checking local spot archive, monthly futures and premium, sampled daily OI.
.venv\Scripts\python.exe research_derivative_sources.py
if errorlevel 1 echo Audit stopped. Send the error above.
pause
