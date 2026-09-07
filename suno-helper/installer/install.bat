@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
echo ========================================
echo   Suno Helper installing...
echo ========================================
echo.

cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found.
    echo.
    echo   1. Install Python 3.11+ from https://www.python.org/downloads/
    echo   2. CHECK "Add python.exe to PATH" during install
    echo   3. Run this installer again
    echo.
    pause
    exit /b 1
)

echo [1/4] Creating virtual environment...
if not exist "backend\.venv" (
    python -m venv backend\.venv
    if errorlevel 1 (
        echo [ERROR] venv creation failed
        pause
        exit /b 1
    )
)

call backend\.venv\Scripts\activate.bat

echo [2/4] Installing packages... (a few minutes)
set PYTHONUTF8=1
python -m pip install -r backend\requirements.txt -q --no-input
if errorlevel 1 (
    echo [ERROR] pip install failed - check internet connection
    pause
    exit /b 1
)

if not exist ".env" (
    copy .env.example .env >nul
)

if not exist "data" mkdir data
if not exist "data\uploads" mkdir data\uploads
if not exist "data\logs" mkdir data\logs

echo [3/4] Registering suno-helper:// protocol...
reg add "HKCU\Software\Classes\suno-helper" /ve /d "URL:Suno Helper Protocol" /f >nul
reg add "HKCU\Software\Classes\suno-helper" /v "URL Protocol" /d "" /f >nul
reg add "HKCU\Software\Classes\suno-helper\shell\open\command" /ve /d "\"%CD%\backend\.venv\Scripts\pythonw.exe\" \"%CD%\launcher.pyw\" \"%%1\"" /f >nul
if errorlevel 1 (
    echo [WARN] protocol registration failed - web launch button may not work
)

echo [4/4] Enabling web launch...
copy /y nul data\web_launch.lock >nul

echo.
echo ========================================
echo   Install complete! Return to your browser.
echo ========================================
echo.
timeout /t 5 >nul
exit /b 0
