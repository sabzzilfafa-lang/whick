@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
echo ========================================
echo   Suno Helper Setup
echo ========================================
echo   This small file downloads the full app
echo   from whick.org and installs it.
echo ========================================
echo.

set "DEST=%LOCALAPPDATA%\SunoHelper"
set "BASE=https://whick.org"

echo [1/3] Creating folder: %DEST%
if not exist "%DEST%" mkdir "%DEST%" || goto :fail

echo [2/3] Downloading app package...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ProgressPreference='SilentlyContinue';" ^
  "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12;" ^
  "$v=(Invoke-RestMethod '%BASE%/api/suno/version' -TimeoutSec 15).data.version;" ^
  "if(-not $v){throw 'version check failed'};" ^
  "Invoke-WebRequest \"%BASE%/dl/suno-helper/v$v/SunoHelper-Setup-v$v.zip\" -OutFile \"$env:TEMP\SunoHelper.zip\" -TimeoutSec 600;" ^
  "Expand-Archive \"$env:TEMP\SunoHelper.zip\" -DestinationPath '%DEST%' -Force;" ^
  "Write-Host ('  downloaded v'+$v)"
if errorlevel 1 goto :fail

rem --- flatten: some zips wrap files in SunoHelper\ subfolder ---
if exist "%DEST%\SunoHelper\install.bat" (
    echo Flattening package layout...
    robocopy "%DEST%\SunoHelper" "%DEST%" /E /MOVE /NFL /NDL /NJH /NJS >nul
    rmdir "%DEST%\SunoHelper" >nul 2>&1
)
if not exist "%DEST%\install.bat" (
    echo [ERROR] install.bat not found after extract.
    goto :fail
)

echo [3/3] Installing (this runs the app's installer)...
cd /d "%DEST%"
call "%DEST%\install.bat"
if errorlevel 1 goto :fail

echo.
echo   Done. Return to your browser tab.
timeout /t 8 >nul
exit /b 0

:fail
echo.
echo [ERROR] Setup failed. Check your internet connection and retry.
pause
exit /b 1
