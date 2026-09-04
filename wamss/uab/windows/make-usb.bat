@echo off
cd /d "%~dp0"
REM Whick USB Maker - HTML GUI (WebView2). Legacy WinForms fallback inside launcher.
if exist "%~dp0Whick-USB-Maker.exe" (
  start "" "%~dp0Whick-USB-Maker.exe"
  exit /b 0
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -Sta -File "%~dp0Whick-USB-Maker-Launcher.ps1"
exit /b %ERRORLEVEL%
