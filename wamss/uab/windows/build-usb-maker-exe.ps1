#Requires -Version 5.1
<#
  Whick USB Maker EXE 빌드 (HTML GUI · WebView2) — 2026-09-02

  Windows에서 관리자 PowerShell로 실행:
    powershell -ExecutionPolicy Bypass -File .\build-usb-maker-exe.ps1

  결과:
    Whick-USB-Maker.exe  — HTML GUI 런처 (UAC 자동 승격)
    → exe + app.html + Whick-USB-Maker.ps1 + Whick-USB-Maker-Launcher.ps1 + ISO 를 같은 폴더에 두고 zip 패킹

  의존: PS2EXE 모듈 (없으면 자동 설치 시도)
#>
$ErrorActionPreference = 'Stop'
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path

# HTML GUI 런처를 EXE로 (requireAdmin → 더블클릭 시 UAC 자동 승격)
$Src = Join-Path $Here 'Whick-USB-Maker-Launcher.ps1'
$Out = Join-Path $Here 'Whick-USB-Maker.exe'

foreach ($f in @('Whick-USB-Maker-Launcher.ps1', 'app.html', 'Whick-USB-Maker.ps1')) {
  if (-not (Test-Path -LiteralPath (Join-Path $Here $f))) {
    throw "필수 파일 없음: $f"
  }
}

function Ensure-PS2EXE {
  $cmd = Get-Command Invoke-PS2EXE -ErrorAction SilentlyContinue
  if ($cmd) { return }
  try {
    Install-PackageProvider -Name NuGet -Force -Scope CurrentUser | Out-Null
  } catch { }
  Install-Module -Name ps2exe -Force -Scope CurrentUser -AllowClobber
  Import-Module ps2exe -Force
  if (-not (Get-Command Invoke-PS2EXE -ErrorAction SilentlyContinue)) {
    throw 'PS2EXE 모듈을 설치하지 못했습니다. https://www.powershellgallery.com/packages/ps2exe'
  }
}

Ensure-PS2EXE
Write-Host "Building $Out (HTML GUI launcher) ..."
Invoke-PS2EXE -inputFile $Src -outputFile $Out -noConsole -requireAdmin `
  -title 'Whick USB Maker' -description 'Whick OS install USB writer (HTML GUI)' `
  -company 'Whick' -product 'Whick USB Maker' -version '0.9.1.0'

if (-not (Test-Path -LiteralPath $Out)) { throw "EXE 생성 실패: $Out" }
Write-Host "OK  $Out ($([math]::Round((Get-Item $Out).Length/1KB)) KB)"
Write-Host ""
Write-Host "다음 파일을 같은 폴더에 두고 배포합니다:"
Write-Host "  Whick-USB-Maker.exe   (이 파일이 실행 진입점)"
Write-Host "  app.html              (HTML UI)"
Write-Host "  Whick-USB-Maker-Launcher.ps1  (EXE 폴백용)"
Write-Host "  Whick-USB-Maker.ps1           (DD 코어)"
Write-Host "  whick-os-live-wired.iso       (설치 이미지)"
Write-Host ""
Write-Host "테스트: Whick-USB-Maker.exe 더블클릭 → UAC 확인 → HTML 창 표시되는지 확인"
