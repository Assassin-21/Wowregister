@echo off
chcp 65001 >nul
cd /d "%~dp0"
".venv\Scripts\python.exe" -X utf8 -m wowregister.registration.replay --macro "data/registration/direct/macro.json" --interactive --timing direct %*
pause
