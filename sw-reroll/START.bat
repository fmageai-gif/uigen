@echo off
title Summoners War Reroll
cd /d "%~dp0"

echo ============================================
echo   Summoners War Reroll
echo ============================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo [X] Python was not found.
    echo.
    echo     Install it from https://www.python.org/downloads/
    echo     and TICK "Add python.exe to PATH" on the first screen.
    echo.
    pause
    exit /b 1
)

python -c "import cv2, yaml, numpy" >nul 2>&1
if errorlevel 1 (
    echo [*] First run - installing what it needs. This takes a minute.
    echo.
    python -m pip install --quiet --upgrade pip
    python -m pip install --quiet -r requirements.txt
    if errorlevel 1 (
        echo.
        echo [X] Install failed. Copy the message above and send it over.
        pause
        exit /b 1
    )
    echo [*] Done.
    echo.
)

python -c "import tkinter" >nul 2>&1
if errorlevel 1 (
    echo [X] Your Python is missing tkinter, so the window cannot open.
    echo     Re-run the Python installer, choose Modify, and tick
    echo     "tcl/tk and IDLE".
    echo.
    pause
    exit /b 1
)

echo [*] Opening the app...
python -m swreroll.gui
if errorlevel 1 (
    echo.
    echo [X] It closed with an error. Copy the message above and send it over.
    pause
)
