@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
echo ========================================
echo   Suno Helper
echo ========================================
echo.

cd /d "%~dp0"

if not exist "backend\.venv" (
    echo [오류] 설치되지 않았습니다. install.bat을 먼저 실행하세요.
    pause
    exit /b 1
)

call backend\.venv\Scripts\activate.bat

if not exist "data\logs" mkdir data\logs

echo   서버 시작 중...
set "ROOT=%~dp0"

netstat -ano | findstr ":8765" | findstr "LISTENING" >nul
if not errorlevel 1 (
    echo   기존 백엔드 종료 후 재시작...
    powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%scripts\kill_backend.ps1" >nul 2>&1
    ping 127.0.0.1 -n 2 >nul
)

powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -Command "Start-Process -FilePath '%ROOT%backend\.venv\Scripts\python.exe' -ArgumentList '%ROOT%backend\run_server.py' -WorkingDirectory '%ROOT%backend' -WindowStyle Hidden"

echo   서버 준비 대기 중...
set /a WAIT=0
:wait_server
ping 127.0.0.1 -n 2 >nul
netstat -ano | findstr ":8765" | findstr "LISTENING" >nul
if not errorlevel 1 goto server_ready
set /a WAIT+=1
if %WAIT% lss 45 goto wait_server
echo [경고] 서버 시작 실패. data\logs\backend.log 확인
pause
exit /b 1

:server_ready
echo.
echo   준비 완료 - 브라우저를 엽니다.
echo   (프로그램은 백그라운드에서 실행됩니다)
echo.
echo   종료: 바탕화면 "Suno Helper - Stop" 또는 stop.bat
echo ========================================
echo.

start http://127.0.0.1:8765
ping 127.0.0.1 -n 3 >nul
exit /b 0
