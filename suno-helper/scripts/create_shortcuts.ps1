# Suno Helper 바탕화면/프로젝트 바로가기 (커스텀 아이콘)
param(
    [string]$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
)

$iconsDir = Join-Path $Root "assets\icons"
$startIco = Join-Path $iconsDir "start.ico"
$stopIco = Join-Path $iconsDir "stop.ico"

if (-not (Test-Path $startIco)) {
    & (Join-Path $PSScriptRoot "generate_icons.ps1") -OutDir $iconsDir
}

$WshShell = New-Object -ComObject WScript.Shell

function New-Shortcut {
    param(
        [string]$LinkPath,
        [string]$Target,
        [string]$Icon,
        [string]$Desc
    )
    $lnk = $WshShell.CreateShortcut($LinkPath)
    $lnk.TargetPath = $Target
    $lnk.WorkingDirectory = $Root
    $lnk.IconLocation = "$Icon,0"
    $lnk.Description = $Desc
    $lnk.Save()
}

New-Shortcut `
    -LinkPath (Join-Path $Root "Suno Helper - Start.lnk") `
    -Target (Join-Path $Root "start.bat") `
    -Icon $startIco `
    -Desc "Suno Helper server start"

New-Shortcut `
    -LinkPath (Join-Path $Root "Suno Helper - Stop.lnk") `
    -Target (Join-Path $Root "stop.bat") `
    -Icon $stopIco `
    -Desc "Suno Helper server stop"

Write-Host "Shortcuts created in $Root"
