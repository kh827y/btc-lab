@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Run start_windows.bat first.
  pause
  exit /b 1
)
.venv\Scripts\python.exe buy_journal.py status
.venv\Scripts\python.exe buy_journal.py settle
if errorlevel 1 echo Settlement failed; existing records retained.
.venv\Scripts\python.exe buy_journal.py issue
if errorlevel 1 echo No new forecast issued. Read the message above.
pause
