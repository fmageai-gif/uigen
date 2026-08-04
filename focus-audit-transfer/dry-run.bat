@echo off
REM Fills ONE entry in the browser and stops before Save, so you can check it.
cd /d "%~dp0"
.venv\Scripts\python.exe transfer.py --dry-run
pause
