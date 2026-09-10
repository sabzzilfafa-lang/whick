@echo off
chcp 65001 >nul
echo.
echo  ■ Suno Helper 서버 종료 중...
echo.

cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\kill_backend.ps1"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\kill_ports.ps1"

echo.
echo  ✓ 종료 완료.
ping 127.0.0.1 -n 3 >nul
