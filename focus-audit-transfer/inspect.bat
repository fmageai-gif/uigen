@echo off
REM Capture the Focus Audit form's fields and dropdown options into form_schema.json.
cd /d "%~dp0"
.venv\Scripts\python.exe transfer.py --inspect
pause
