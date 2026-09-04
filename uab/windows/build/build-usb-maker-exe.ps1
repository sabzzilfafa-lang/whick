#Requires -Version 5.1
<#
  Whick USB Maker EXE build (HTML GUI / WebView2) - 2026-09-02

  Run this on Windows with normal PowerShell (no admin needed):
      powershell -ExecutionPolicy Bypass -File .\build\build-usb-maker-exe.ps1
  or double-click build\build-usb-maker.bat

  Result: build\Whick-USB-Maker.exe  (HTML GUI launcher, auto UAC)

  Then move the exe to the zip root (same folder as the ISO):
      move .\build\Whick-USB-Maker.exe .\Whick-USB-Maker.exe

  Needs internet once (PS2EXE + WebView2 SDK auto-download).
#>
$ErrorActionPreference = 'Stop'
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path   # build\
if ([string]::IsNullOrWhiteSpace($ScriptDir)) {
  $ScriptDir = Split-Path -Parent (Get-Process -Id $PID).Path
}
$ZipRoot = Split-Path -Parent $ScriptDir                        # zip root (ISO location)
$Out = Join-Path $ScriptDir 'Whick-USB-Maker.exe'
$SrcLauncher = Join-Path $ZipRoot 'Whick-USB-Maker-Launcher.ps1'

foreach ($f in @('Whick-USB-Maker-Launcher.ps1', 'app.html', 'Whick-USB-Maker.ps1')) {
  if (-not (Test-Path -LiteralPath (Join-Path $ZipRoot $f))) {
    throw "missing file in zip root: $f"
  }
}

Write-Host '=== Whick USB Maker EXE build ==='
Write-Host "zip root: $ZipRoot"

# ---- 1) PS2EXE ----
function Ensure-PS2EXE {
  $cmd = Get-Command Invoke-PS2EXE -ErrorAction SilentlyContinue
  if ($cmd) { return }
  Write-Host 'Installing PS2EXE module (internet, once)...'
  try { Install-PackageProvider -Name NuGet -Force -Scope CurrentUser | Out-Null } catch { }
  Install-Module -Name ps2exe -Force -Scope CurrentUser -AllowClobber
  Import-Module ps2exe -Force
  if (-not (Get-Command Invoke-PS2EXE -ErrorAction SilentlyContinue)) {
    throw 'PS2EXE install failed - check https://www.powershellgallery.com/packages/ps2exe'
  }
}
Ensure-PS2EXE

# ---- 2) WebView2 .NET SDK from NuGet ----
$wv2Dir = Join-Path $ScriptDir 'wv2'
$wantDlls = @('Microsoft.Web.WebView2.Core.dll','Microsoft.Web.WebView2.WinForms.dll','Microsoft.Web.WebView2.Loader.dll')
# 네이티브 로더 (P/Invoke 대상) - 파일명에 버전 접미사가 붙을 수 있아 와일드카드로 검색
$nativeLoader = 'WebView2Loader.dll'
$haveAll = $true
foreach ($d in $wantDlls) {
  if (-not (Get-ChildItem -Path $wv2Dir -Recurse -Filter $d -ErrorAction SilentlyContinue | Select-Object -First 1)) { $haveAll = $false }
}
if (-not $haveAll) {
  Write-Host 'Downloading WebView2 SDK (internet, once)...'
  $nugetUrl = 'https://www.nuget.org/api/v2/package/Microsoft.Web.WebView2/1.0.2903.40'
  $nupkg = Join-Path $env:TEMP 'Microsoft.Web.WebView2.zip'
  [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
  Invoke-WebRequest -Uri $nugetUrl -OutFile $nupkg -UseBasicParsing
  if (Test-Path $wv2Dir) { Remove-Item $wv2Dir -Recurse -Force }
  Expand-Archive -LiteralPath $nupkg -DestinationPath $wv2Dir -Force
  Remove-Item $nupkg -Force -ErrorAction SilentlyContinue
}

# ---- 3) copy SDK DLLs next to the exe (recursive search - no path guessing) ----
$copied = 0
foreach ($d in $wantDlls) {
  $hit = Get-ChildItem -Path $wv2Dir -Recurse -Filter $d -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($hit) {
    Copy-Item $hit.FullName (Join-Path $ZipRoot $d) -Force
    Write-Host "  + $d"
    $copied++
  }
}
# native loader: pick the one matching THIS process architecture (BadImageFormat prevention)
$nativeArch = 'win-x86'
if ([Environment]::Is64BitOperatingSystem) { $nativeArch = 'win-x64' }
if ([Environment]::Is64BitProcess -eq $false -and [Environment]::Is64BitOperatingSystem) { $nativeArch = 'win-x86' }
$nativeHit = Get-ChildItem -Path $wv2Dir -Recurse -Filter $nativeLoader -ErrorAction SilentlyContinue |
  Where-Object { $_.FullName -match [regex]::Escape($nativeArch) } | Select-Object -First 1
if ($nativeHit) {
  Copy-Item $nativeHit.FullName (Join-Path $ZipRoot $nativeLoader) -Force
  Write-Host "  + $nativeLoader (native $nativeArch, from $($nativeHit.Directory.Name))"
  $copied++
} else {
  Write-Host "  ! native $nativeArch loader not found - trying any arch"
  $nativeHit = Get-ChildItem -Path $wv2Dir -Recurse -Filter $nativeLoader -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -match 'win-(x64|x86|arm64)' } | Select-Object -First 1
  if ($nativeHit) { Copy-Item $nativeHit.FullName (Join-Path $ZipRoot $nativeLoader) -Force; $copied++ }
}
if ($copied -lt 3) { throw "WebView2 SDK DLLs not found in $wv2Dir (copied $copied) - delete the wv2 folder and retry" }

# ---- 4) compile EXE ----
Write-Host 'Building EXE...'
Invoke-PS2EXE -inputFile $SrcLauncher -outputFile $Out -noConsole -requireAdmin `
  -title 'Whick USB Maker' -description 'Whick OS install USB writer (HTML GUI)' `
  -company 'Whick' -product 'Whick USB Maker' -version '0.9.1.0'

if (-not (Test-Path -LiteralPath $Out)) { throw 'EXE build failed' }
Write-Host "OK  $Out ($([math]::Round((Get-Item $Out).Length/1KB)) KB)"
Write-Host ''
Write-Host '=== next steps ==='
Write-Host "1) move the EXE to the zip root:"
Write-Host "   move `"$Out`" `"$ZipRoot\Whick-USB-Maker.exe`""
Write-Host '2) double-click Whick-USB-Maker.exe - the HTML window should open'
Write-Host '3) if it works, send the exe file back'
