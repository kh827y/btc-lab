@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Run start_windows.bat once before downloading.
  pause
  exit /b 1
)
.venv\Scripts\python.exe extended_history.py
if errorlevel 1 echo Some downloads failed. Existing archives were retained.
pause
