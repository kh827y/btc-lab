@echo off
cd /d "%~dp0"
where py >nul 2>&1
if not errorlevel 1 (
  set "PYTHON=py -3"
) else (
  where python >nul 2>&1
  if errorlevel 1 (
    echo Python 3 not found. Install it from https://www.python.org/downloads/
    pause
    exit /b 1
  )
  set "PYTHON=python"
)
if not exist .venv\Scripts\python.exe (
  echo Creating Python environment...
  %PYTHON% -m venv .venv
  if errorlevel 1 goto :error
)
echo Installing or updating dependencies...
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto :error
echo Starting local BTC panel. To close it, press Ctrl+C here.
.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501
if errorlevel 1 goto :error
exit /b 0
:error
echo Something went wrong. Review the error messages above.
pause
exit /b 1
