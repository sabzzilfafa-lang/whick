# Kill all Suno Helper backend/frontend listeners
$ports = @(8765, 5173)
$maxRounds = 5
for ($round = 1; $round -le $maxRounds; $round++) {
    foreach ($port in $ports) {
        $pids = @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty OwningProcess -Unique)
        foreach ($procId in $pids) {
            if (-not $procId) { continue }
            Write-Host "Stopping PID $procId on port $port (round $round)"
            Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
            Get-CimInstance Win32_Process -Filter "ParentProcessId=$procId" -ErrorAction SilentlyContinue |
                ForEach-Object {
                    Write-Host "  child PID $($_.ProcessId)"
                    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
                }
        }
    }

    Get-CimInstance Win32_Process -Filter "name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and ($_.CommandLine -match 'run_server\.py' -or $_.CommandLine -match 'app\.main:app') } |
        ForEach-Object {
            Write-Host "Stopping python $($_.ProcessId)"
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        }

    Start-Sleep -Milliseconds 800
    $remaining8765 = @(Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue)
    if (-not $remaining8765) { break }
}

$remaining = Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue
if ($remaining) {
    Write-Host "WARN: port 8765 still in use"
    $remaining | Format-Table OwningProcess, LocalPort
    exit 1
}
Write-Host "Port 8765 is free"
exit 0
