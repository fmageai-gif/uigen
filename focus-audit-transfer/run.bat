@echo off
REM Daily transfer. Pass extra options straight through, e.g. run.bat --dry-run
cd /d "%~dp0"
.venv\Scripts\python.exe transfer.py %*
pause
