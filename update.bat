@echo off
cd /d "%~dp0"
git pull --ff-only
if errorlevel 1 (
  echo Update failed. Send the error to ChatGPT.
  pause
  exit /b 1
)
echo Update complete. Start the panel with start_windows.bat.
pause
