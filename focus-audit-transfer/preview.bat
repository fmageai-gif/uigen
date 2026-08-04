@echo off
REM Safe: reads the workbook and prints what WOULD be sent. Submits nothing.
cd /d "%~dp0"
.venv\Scripts\python.exe transfer.py --preview
pause
