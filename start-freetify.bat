@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Freetify is not installed yet. Run install-windows.ps1 with PowerShell.
  pause
  exit /b 1
)
start "Freetify server" /min "%~dp0.venv\Scripts\python.exe" "%~dp0server.py"
powershell -NoProfile -Command "Start-Sleep -Seconds 1"
start "" "http://127.0.0.1:8000"
