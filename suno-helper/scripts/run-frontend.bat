@echo off
chcp 65001 >nul
set "ROOT=%~dp0.."
cd /d "%ROOT%\frontend"
if not exist "%ROOT%\data\logs" mkdir "%ROOT%\data\logs"

set "NPM=npm"
where npm >nul 2>&1
if errorlevel 1 (
    if exist "%ProgramFiles%\nodejs\npm.cmd" set "NPM=%ProgramFiles%\nodejs\npm.cmd"
    if exist "%ProgramFiles(x86)%\nodejs\npm.cmd" set "NPM=%ProgramFiles(x86)%\nodejs\npm.cmd"
)

call "%NPM%" run dev >> "%ROOT%\data\logs\frontend.log" 2>&1
