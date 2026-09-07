$d = "$env:LOCALAPPDATA\SunoHelper"
Write-Host "venv python: $(Test-Path "$d\backend\.venv\Scripts\python.exe")"
Write-Host "lock: $(Test-Path "$d\data\web_launch.lock")"
Write-Host "backend.log tail:"
Get-Content "$d\data\logs\backend.log" -Tail 5 -ErrorAction SilentlyContinue
Write-Host "backend.err tail:"
Get-Content "$d\data\logs\backend.err" -Tail 5 -ErrorAction SilentlyContinue
Write-Host "port 8765:"
netstat -ano | findstr ":8765" | findstr "LISTENING"
