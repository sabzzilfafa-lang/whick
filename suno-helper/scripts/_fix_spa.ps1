# 설치본에 수정 main.py 반영 + 백엔드 재시작 + SPA 폴백 검증
$src = "c:\Users\user\suno_helper\backend\app\main.py"
$dst = "$env:LOCALAPPDATA\SunoHelper\backend\app\main.py"
Copy-Item $src $dst -Force
Write-Host "copied main.py"

# 백엔드 종료 (8765 리스너)
$conn = Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue
if ($conn) {
    $conn | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 2
    Write-Host "old backend killed"
}
# 재기동
Start-Process -FilePath "$env:LOCALAPPDATA\SunoHelper\backend\.venv\Scripts\python.exe" `
  -ArgumentList "$env:LOCALAPPDATA\SunoHelper\backend\run_server.py" `
  -WorkingDirectory "$env:LOCALAPPDATA\SunoHelper\backend" -WindowStyle Hidden
Start-Sleep -Seconds 8

# 검증
Write-Host "== SPA fallback checks =="
foreach ($u in @("/", "/albums", "/albums/1", "/settings", "/api/albums")) {
    try {
        $r = Invoke-WebRequest "http://127.0.0.1:8765$u" -UseBasicParsing -TimeoutSec 10
        $ct = $r.Headers["Content-Type"]
        Write-Host ("{0,-12} {1} {2}" -f $u, $r.StatusCode, ($ct -join ""))
    } catch {
        Write-Host ("{0,-12} {1}" -f $u, $_.Exception.Response.StatusCode.value__)
    }
}
