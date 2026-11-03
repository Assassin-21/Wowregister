@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo Run setup_registration.cmd first, or use the packaged Wowregister.exe.
  pause
  exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" -m wowregister.panel
