@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
echo ========================================
echo   Suno Helper 설치 (v1.0.0)
echo ========================================
echo.

cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
    echo [오류] Python이 설치되어 있지 않습니다.
    echo.
    echo   1. https://www.python.org/downloads/ 에서 Python 3.11+ 설치
    echo   2. 설치 시 "Add python.exe to PATH" 체크 필수
    echo   3. 이 스크립트를 다시 실행
    echo.
    pause
    exit /b 1
)

echo [1/3] Python 가상환경 생성 중...
if not exist "backend\.venv" (
    python -m venv backend\.venv
    if errorlevel 1 (
        echo [오류] 가상환경 생성 실패
        pause
        exit /b 1
    )
)

call backend\.venv\Scripts\activate.bat

echo [2/3] 백엔드 패키지 설치 중... (数분 소요)
set PYTHONUTF8=1
python -m pip install -r backend\requirements.txt -q --no-input
if errorlevel 1 (
    echo [오류] 패키지 설치 실패 - 인터넷 연결을 확인하세요
    pause
    exit /b 1
)

if not exist ".env" (
    copy .env.example .env >nul
)

if not exist "data" mkdir data
if not exist "data\uploads" mkdir data\uploads
if not exist "data\logs" mkdir data\logs

echo [3/3] 바로가기 생성 중...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ws = New-Object -ComObject WScript.Shell;" ^
  "$s = $ws.CreateShortcut([Environment]::GetFolderPath('Desktop') + '\Suno Helper.lnk');" ^
  "$s.TargetPath = '%~dp0start.bat';" ^
  "$s.WorkingDirectory = '%~dp0';" ^
  "$s.Description = 'Suno Helper 실행';" ^
  "$s.Save()"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ws = New-Object -ComObject WScript.Shell;" ^
  "$s = $ws.CreateShortcut([Environment]::GetFolderPath('Desktop') + '\Suno Helper - Stop.lnk');" ^
  "$s.TargetPath = '%~dp0stop.bat';" ^
  "$s.WorkingDirectory = '%~dp0';" ^
  "$s.Description = 'Suno Helper 종료';" ^
  "$s.Save()"

echo.
echo ========================================
echo   설치 완료!
echo.
echo   시작: 바탕화면 "Suno Helper" 바로가기
echo   (또는 start.bat 실행)
echo ========================================
echo.
pause
