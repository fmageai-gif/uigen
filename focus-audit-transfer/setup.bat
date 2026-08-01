@echo off
REM One-time setup. Run this once before using run.bat.
cd /d "%~dp0"

echo Creating the Python environment...
python -m venv .venv || goto :fail

echo Installing packages...
.venv\Scripts\python.exe -m pip install --quiet --upgrade pip || goto :fail
.venv\Scripts\python.exe -m pip install --quiet -r requirements.txt || goto :fail

echo Setting up the browser driver...
.venv\Scripts\python.exe -m playwright install msedge

echo.
echo Setup finished. Run inspect.bat next.
pause
exit /b 0

:fail
echo.
echo Setup failed. Make sure Python 3.10 or newer is installed and on your PATH.
pause
exit /b 1
