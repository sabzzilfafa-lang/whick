param([string]$LocalFile, [string]$RemotePath)
# 로컬 파일을 LF+UTF-8(no BOM)로 변환해 서버로 전송·실행하는 헬퍼
# 사용: powershell -File _convert.ps1 -LocalFile <경로> -RemotePath /tmp/xxx.sh
$rr = (Get-Content $LocalFile -Raw) -replace "`r`n","`n"
$tmp = "$env:TEMP\_converted_" + (Split-Path $LocalFile -Leaf)
[System.IO.File]::WriteAllText($tmp, $rr, (New-Object System.Text.UTF8Encoding($false)))
if ($RemotePath) {
    cmd /c "scp -q $tmp whick-server:$RemotePath"
    "sent to whick-server:$RemotePath"
} else {
    "converted: $tmp"
}
