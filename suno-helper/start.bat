@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
echo ========================================
echo   ♪ Suno Helper - 수노 음악 제작 도우미
echo ========================================
echo.

cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
    echo [오류] Python이 설치되어 있지 않습니다.
    echo https://www.python.org/downloads/
    pause
    exit /b 1
)

where node >nul 2>&1
if errorlevel 1 (
    echo [오류] Node.js가 설치되어 있지 않습니다.
    echo https://nodejs.org/
    pause
    exit /b 1
)

if not exist "backend\.venv" (
    echo [1/4] Python 가상환경 생성 중...
    python -m venv backend\.venv
    if errorlevel 1 (
        echo [오류] 가상환경 생성 실패
        pause
        exit /b 1
    )
)

call backend\.venv\Scripts\activate.bat

echo [2/4] 백엔드 패키지 확인 중...
pip install -r backend\requirements.txt -q

if not exist ".env" (
    copy .env.example .env >nul
    echo  .env 파일이 생성되었습니다. 앱 내 '사용자 설정'에서 API 키를 입력하세요.
)

if not exist "frontend\node_modules" (
    echo [3/4] 프론트엔드 패키지 설치 중...
    cd frontend
    call npm install
    if errorlevel 1 (
        echo [오류] npm install 실패
        cd ..
        pause
        exit /b 1
    )
    cd ..
) else (
    echo [3/4] 프론트엔드 패키지 확인 완료
)

if not exist "data" mkdir data
if not exist "data\uploads" mkdir data\uploads
if not exist "data\logs" mkdir data\logs

echo [4/4] 서버 시작 중 (백그라운드)...
set "ROOT=%~dp0"

netstat -ano | findstr ":8765" | findstr "LISTENING" >nul
if not errorlevel 1 (
    echo   기존 백엔드 종료 후 재시작...
    powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%scripts\kill_backend.ps1" >nul 2>&1
    ping 127.0.0.1 -n 2 >nul
)
powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -Command "Start-Process -FilePath '%ROOT%backend\.venv\Scripts\python.exe' -ArgumentList '%ROOT%backend\run_server.py' -WorkingDirectory '%ROOT%backend' -WindowStyle Hidden"
echo   백엔드 시작됨

netstat -ano | findstr ":5173" | findstr "LISTENING" >nul
if errorlevel 1 (
    powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -Command "Start-Process -FilePath 'cmd.exe' -ArgumentList '/c','npm run dev 1>> \"%ROOT%data\logs\frontend.log\" 2>>&1' -WorkingDirectory '%ROOT%frontend' -WindowStyle Hidden"
    echo   프론트엔드 시작 중...
) else (
    echo   프론트: 이미 실행 중
)

echo   서버 준비 대기 중...
set /a WAIT=0
:wait_servers
ping 127.0.0.1 -n 2 >nul
set BACKEND_OK=0
set FRONTEND_OK=0
netstat -ano | findstr ":8765" | findstr "LISTENING" >nul
if not errorlevel 1 set BACKEND_OK=1
netstat -ano | findstr ":5173" | findstr "LISTENING" >nul
if not errorlevel 1 set FRONTEND_OK=1
if !BACKEND_OK!==1 if !FRONTEND_OK!==1 goto servers_ready
set /a WAIT+=1
if %WAIT% lss 45 goto wait_servers

if !BACKEND_OK!==0 echo [경고] 백엔드 시작 실패. data\logs\backend.log 확인
if !FRONTEND_OK!==0 echo [경고] 프론트 시작 실패. data\logs\frontend.log 확인

:servers_ready
echo   백엔드: http://127.0.0.1:8765
echo   프론트: http://127.0.0.1:5173
:open_browser
echo.
echo ========================================
echo   준비 완료 - 브라우저를 엽니다.
echo   종료: Suno Helper - Stop.lnk 또는 stop.bat
echo   로그: data\logs\
echo ========================================
echo.

start http://127.0.0.1:5173
ping 127.0.0.1 -n 3 >nul
