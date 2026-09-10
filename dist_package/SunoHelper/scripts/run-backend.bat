@echo off
chcp 65001 >nul
set "ROOT=%~dp0.."
cd /d "%ROOT%"
if not exist "data\logs" mkdir "data\logs"
"%ROOT%\backend\.venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8765 --reload --app-dir "%ROOT%\backend" >> "%ROOT%\data\logs\backend.log" 2>&1
