@echo off
cd /d "%~dp0"
.venv\Scripts\python.exe -I -S -B refresh_local_bridge.py
pause
