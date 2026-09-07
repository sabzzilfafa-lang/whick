param([string]$LocalFile, [string]$RemotePath)
# Convert local file to LF + UTF-8 (no BOM) and optionally send to whick-server
# Usage: powershell -File _convert.ps1 -LocalFile <path> -RemotePath /tmp/xxx.sh
$rr = (Get-Content $LocalFile -Raw) -replace "`r`n","`n"
$tmp = "$env:TEMP\_converted_" + (Split-Path $LocalFile -Leaf)
[System.IO.File]::WriteAllText($tmp, $rr, (New-Object System.Text.UTF8Encoding($false)))
if ($RemotePath) {
    cmd /c "scp -q $tmp whick-server:$RemotePath"
    "sent to whick-server:$RemotePath"
} else {
    "converted: $tmp"
}
