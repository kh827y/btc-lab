@echo off
setlocal
cd /d "%~dp0"
if exist app.py (
  echo Panel source already exists here. Import skipped.
  pause
  exit /b 1
)
set "SRC=%~dp0..\btc-market-panel"
if not "%~1"=="" set "SRC=%~1"
if not exist "%SRC%\app.py" goto :missing
for %%F in (app.py data_logic.py requirements.txt start_windows.bat ARCHITECTURE.md AGENTS.md README.md .streamlit\config.toml tests\test_data_logic.py data\README.txt) do (
  if not exist "%SRC%\%%F" (
    echo Missing required file: %%F
    goto :error
  )
)
git pull --ff-only
if errorlevel 1 goto :error
if exist app.py goto :error
for %%F in (app.py data_logic.py requirements.txt start_windows.bat ARCHITECTURE.md AGENTS.md) do (
  copy /Y "%SRC%\%%F" "%%F" >nul
  if errorlevel 1 goto :error
)
copy /Y "%SRC%\README.md" PANEL_README.md >nul
if errorlevel 1 goto :error
if not exist .streamlit mkdir .streamlit
if not exist tests mkdir tests
if not exist data mkdir data
for %%F in (.streamlit\config.toml tests\test_data_logic.py data\README.txt) do (
  copy /Y "%SRC%\%%F" "%%F" >nul
  if errorlevel 1 goto :error
)
git add -- app.py data_logic.py requirements.txt start_windows.bat ARCHITECTURE.md AGENTS.md PANEL_README.md .streamlit/config.toml tests/test_data_logic.py data/README.txt
if errorlevel 1 goto :error
git -c user.name=kh827y -c user.email=225114003+kh827y@users.noreply.github.com commit -m "Import existing BTC Market Panel v2"
if errorlevel 1 goto :error
git push origin main
if errorlevel 1 (
  echo Commit saved locally. Retry with git push origin main.
  pause
  exit /b 1
)
echo Panel imported. Start with start_windows.bat.
pause
exit /b 0
:missing
echo Source folder not found: "%SRC%"
echo Run import_panel.bat with the full path to the existing panel folder.
:error
echo Import stopped. No secrets or local caches are selected for upload.
pause
exit /b 1
