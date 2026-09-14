@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Freetify is not installed yet. Run install-windows.ps1 with PowerShell.
  pause
  exit /b 1
)
start "Freetify" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0server.py"
