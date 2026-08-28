@echo off
chcp 65001 >nul
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\create_shortcuts.ps1"
echo.
echo 바로가기가 생성되었습니다:
echo   - Suno Helper - Start.lnk  (보라색 재생 아이콘)
echo   - Suno Helper - Stop.lnk   (빨간 정지 아이콘)
echo.
pause
