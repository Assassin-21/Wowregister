@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Missing Python environment. See README.md.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -X utf8 -m wowregister.registration.replay --interactive %*
pause
