@echo off
chcp 65001 >nul
rem Suno Helper - local direct launch guard
rem This app must be started from https://whick.org/suno.html (web dashboard).
rem Direct execution is intentionally blocked for license compliance.

cd /d "%~dp0"

if exist "data\web_launch.lock" (
    echo.
    echo  ============================================
    echo   Suno Helper runs from the web dashboard.
    echo.
    echo   1. Open  https://whick.org/suno.html
    echo   2. Sign in, then click the Run button.
    echo  ============================================
    echo.
) else (
    echo.
    echo  ============================================
    echo   Please complete installation first.
    echo   Visit https://whick.org/suno.html
    echo  ============================================
    echo.
)
timeout /t 10 >nul
exit /b 1
