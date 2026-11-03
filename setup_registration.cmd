@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  python -m venv .venv
  if errorlevel 1 goto failed
)
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
echo Setup complete. See docs/LICENSING.md for activation.
pause
exit /b 0
:failed
echo Setup failed. Install Python 3.11 or newer and retry.
pause
exit /b 1
