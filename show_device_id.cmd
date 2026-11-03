@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run setup_registration.cmd first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -X utf8 -m wowregister.licensing.client --device-id
pause
