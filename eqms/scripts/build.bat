@echo off
REM ============================================================
REM  HP Mainstream EQMS - Windows build script
REM  Produces dist\HP-Mainstream-EQMS.exe (single-file, no Python required)
REM ============================================================
setlocal

echo.
echo === HP Mainstream EQMS build ===
echo.

REM Prefer Python 3.13 launcher if available.
where py >nul 2>nul
if %errorlevel%==0 (
    set PY=py -3.13
) else (
    set PY=python
)

echo Using interpreter: %PY%
echo.

echo [1/3] Creating virtual environment (.venv) ...
%PY% -m venv .venv
call .venv\Scripts\activate.bat

echo [2/3] Installing dependencies ...
python -m pip install --upgrade pip
pip install -r requirements.txt

echo [3/3] Building executable ...
python scripts\build.py --clean

echo.
echo Done. See dist\HP-Mainstream-EQMS.exe
endlocal
pause
