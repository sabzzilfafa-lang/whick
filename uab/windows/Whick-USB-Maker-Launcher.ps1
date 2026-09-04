#Requires -Version 5.1
<#
  Whick USB Maker — WebView2 HTML UI 런처 (2026-09-02)

  구조:
    - 관리자 권한 확인(UAC) → WebView2로 app.html 표시
    - app.html JS → window.chrome.webview.postMessage(cmd) → 런처 처리
    - 진행률·상태는 UI 스레드 타이머로 안전하게 전송 (writes 큐)
    - DD 기록은 기존 Whick-USB-Maker.ps1의 검증된 Write-WhickIsoToPhysicalDrive 재사용
#>

param(
  [string]$AppHtml = ""
)

$ErrorActionPreference = "Stop"
# PS2EXE 컴파일 EXE에서는 $MyInvocation.MyCommand.Path가 null → Split-Path가 Stop으로 즉사하므로 try/catch 필수
$Here = $null
try { $Here = Split-Path -Parent $MyInvocation.MyCommand.Path } catch { $Here = $null }
if ([string]::IsNullOrWhiteSpace($Here)) {
  try { $Here = Split-Path -Parent (Get-Process -Id $PID).Path } catch { $Here = $null }
}
if ([string]::IsNullOrWhiteSpace($Here)) { $Here = (Get-Location).Path }
if (-not $AppHtml) { $AppHtml = Join-Path $Here "app.html" }
$LogPath = Join-Path $Here "Whick-USB-Maker.log"

function Write-WhickLog {
  param([string]$Message)
  try { Add-Content -LiteralPath $LogPath -Value ("{0} {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message) -Encoding UTF8 } catch { }
}

# ── 관리자 권한 (UAC 승격 — 한 번만) ──
$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
  $psArgs = @('-NoProfile','-ExecutionPolicy','Bypass','-WindowStyle','Hidden','-Sta','-File', "`"$PSCommandPath`"", '-AppHtml', "`"$AppHtml`"")
  try {
    Start-Process -FilePath 'powershell.exe' -Verb RunAs -WindowStyle Hidden -ArgumentList $psArgs | Out-Null
  } catch {
    # UAC 거부 — 조용히 종료
  }
  exit 0
}

try {

Write-WhickLog "launcher start pid=$PID"

# ── WebView2 런타임 확인 ──
$wv2 = Get-ItemProperty 'HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}' -ErrorAction SilentlyContinue
if (-not $wv2) {
  $wv2 = Get-ItemProperty 'HKCU:\Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}' -ErrorAction SilentlyContinue
}
if (-not $wv2) {
  $errHtml = Join-Path $env:TEMP "whick-usbmaker-webview2-required.html"
  @"
<!DOCTYPE html><html><head><meta charset="utf-8"><title>Whick USB Maker</title>
<style>body{font-family:'Malgun Gothic',sans-serif;background:#0f1419;color:#e8ecf1;display:flex;align-items:center;justify-content:center;height:100vh;margin:0}
.c{max-width:520px;padding:32px;background:#1a2332;border-radius:14px}
h1{font-size:20px;margin:0 0 12px}
p{font-size:14px;line-height:1.7;color:#aab4c4}
a{color:#4da3ff}</style></head>
<body><div class="c">
<h1>Whick USB Maker 실행에 필요한 구성요소</h1>
<p>Microsoft Edge WebView2 Runtime이 필요합니다.<br>
Microsoft Edge WebView2 Runtime is required.</p>
<p><a href="https://go.microsoft.com/fwlink/p/?LinkId=2124703">WebView2 Runtime 다운로드 / Download WebView2 Runtime</a></p>
<p style="font-size:12px">설치 후 make-usb.bat을 다시 실행해 주세요.<br>Please run make-usb.bat again after installing.</p>
</div></body></html>
"@ | Out-File -LiteralPath $errHtml -Encoding UTF8
  Start-Process $errHtml
  exit 1
}

# ── 기존 검증된 DD 기록 코어 로드 (함수만 필요 — GUI 진입 코드는 조건부 스킵) ──
# PS2EXE 환경: 시스템 실행정책(Restricted)이면 dot-source 차단됨 → 3단계 폴백
$env:WHICK_USB_CORE_ONLY = "1"
$corePath = Join-Path $Here "Whick-USB-Maker.ps1"
$coreLoaded = $false

# 1) 직접 dot-source
try { . $corePath; $coreLoaded = $true } catch {
  Write-WhickLog "dot-source blocked ($($_.Exception.Message))"
}

# 2) 프로세스 범위 실행정책 완화 (프로세스 종료 시 자동 원복, 관리자 불필요)
if (-not $coreLoaded) {
  try {
    Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
    . $corePath; $coreLoaded = $true
    Write-WhickLog "core loaded after Process-scope Bypass"
  } catch { Write-WhickLog "Process Bypass failed: $($_.Exception.Message)" }
}

# 3) 파일 실행 없이 문자열로 로드 — 실행정책 파일 검사를 거치지 않음
if (-not $coreLoaded) {
  try {
    . ([scriptblock]::Create((Get-Content -LiteralPath $corePath -Raw -Encoding UTF8)))
    $coreLoaded = $true
    Write-WhickLog "core loaded via scriptblock::Create"
  } catch { Write-WhickLog ("scriptblock load failed: " + $_.Exception.Message) }
}

Remove-Item Env:\WHICK_USB_CORE_ONLY -ErrorAction SilentlyContinue
if (-not $coreLoaded) { throw "Whick-USB-Maker.ps1 로드 실패 / failed to load core script (execution policy)" }

function Get-WhickIsoPath {
  foreach ($c in @(
    (Join-Path $Here "whick-os-live-wireless.iso"),
    (Join-Path $Here "whick-os-live-wired.iso")
  )) {
    if (Test-Path -LiteralPath $c) { return $c }
  }
  return $null
}

# ── UI 스레드 안전 메시지 큐 (작업 스레드 → UI 타이머 → WebView) ──
$sync = [hashtable]::Synchronized(@{
  Messages = New-Object System.Collections.Queue
  Wv       = $null
  Form     = $null
  Busy     = $false
})

function Send-Ui {
  param([hashtable]$Data)
  try {
    $sync.Messages.Enqueue($Data)
  } catch { Write-WhickLog "Send-Ui enqueue fail: $($_.Exception.Message)" }
}

function Get-UsbList {
  try { Sync-StorageCache } catch { Write-WhickLog "storage cache fail: $($_.Exception.Message)" }
  $items = @()
  try {
    $disks = @(Get-UsbDisks)
    Write-WhickLog ("usb disks found: " + $disks.Count)
    foreach ($d in $disks) {
      try {
        $items += ,@{
          number  = [int]$d.Number
          name    = [string]$d.FriendlyName
          size_gb = [math]::Round($d.Size / 1GB, 1)
        }
      } catch { Write-WhickLog "disk map fail: $($_.Exception.Message)" }
    }
  } catch {
    Write-WhickLog ("Get-UsbDisks fail: " + $_.Exception.Message)
  }
  Write-WhickLog ("usb items mapped: " + $items.Count)
  $iso = Get-WhickIsoPath
  return @{
    type   = "usb-list"
    disks  = $items
    iso    = $(if ($iso) { Split-Path -Leaf $iso } else { "" })
    iso_ok = [bool]$iso
  }
}

# ── 쓰기 작업 (백그라운드 스레드) ──
$writeScript = {
  param($syncTable, $diskNum, $isoPath, $logPath, $corePath)
  function Write-WhickLog2 {
    param([string]$Message)
    try { Add-Content -LiteralPath $logPath -Value ("{0} [write] {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message) -Encoding UTF8 } catch { }
  }
  try {
    Write-WhickLog2 "write start disk=$diskNum iso=$isoPath core=$corePath"
    if (-not (Test-Path -LiteralPath $corePath)) { throw "core script missing: $corePath" }
    # 코어 파일 전체를 이 runspace에 도트소싱 (CORE_ONLY guard로 GUI 진입 없이 함수만 로드)
    # 함수 정의가 모두 여기 세션에 생기므로 cross-runspace 바인딩 문제 없음
    $env:WHICK_USB_CORE_ONLY = "1"
    . ([scriptblock]::Create((Get-Content -LiteralPath $corePath -Raw -Encoding UTF8)))
    Remove-Item Env:\WHICK_USB_CORE_ONLY -ErrorAction SilentlyContinue
    $coreFn = Get-Command 'Write-WhickIsoToPhysicalDrive' -ErrorAction SilentlyContinue
    Write-WhickLog2 ("core functions loaded: " + $(if ($coreFn) { 'yes' } else { 'NO' }))
    if (-not $coreFn) { throw 'Write-WhickIsoToPhysicalDrive not defined after dot-sourcing' }
    & $coreFn -DiskNum $diskNum -IsoPath $isoPath -OnProgress {
      param($Message, [int]$Percent = -1)
      $ko = [string]$Message; $en = ""
      $nl = $ko.IndexOf("`n")
      if ($nl -ge 0) { $en = $ko.Substring($nl + 1); $ko = $ko.Substring(0, $nl) }
      $syncTable.Messages.Enqueue(@{ type = "progress"; pct = $Percent; message_ko = $ko; message_en = $en })
    }
    Write-WhickLog2 "write complete disk=$diskNum"
    $syncTable.Messages.Enqueue(@{ type = "write-complete"; disk = "PhysicalDrive$diskNum" })
  } catch {
    Write-WhickLog2 "write error: $($_.Exception.Message)"
    $m = [string]$_.Exception.Message
    $ko = $m; $en = ""
    $nl = $m.IndexOf("`n")
    if ($nl -ge 0) { $en = $m.Substring($nl + 1); $ko = $m.Substring(0, $nl) }
    $syncTable.Messages.Enqueue(@{ type = "write-error"; message_ko = $ko; message_en = $en })
  } finally {
    $syncTable.Busy = $false
  }
}

# ── WebView2 폼 ──
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$form = New-Object System.Windows.Forms.Form
$form.Text = "Whick USB Maker"
$form.Size = New-Object System.Drawing.Size(780, 640)
$form.StartPosition = "CenterScreen"
$form.FormBorderStyle = "FixedDialog"
$form.MaximizeBox = $false
$form.BackColor = [System.Drawing.Color]::FromArgb(13, 17, 23)

# WebView2 .NET SDK DLL 로드 (EXE 옆 배포 — build-usb-maker-exe.ps1이 NuGet에서 받아 옴)
foreach ($wvDll in @('Microsoft.Web.WebView2.Core.dll','Microsoft.Web.WebView2.WinForms.dll','Microsoft.Web.WebView2.Loader.dll')) {
  $wvPath = Join-Path $Here $wvDll
  if (Test-Path -LiteralPath $wvPath) {
    try { Add-Type -Path $wvPath } catch { Write-WhickLog "Add-Type fail $wvDll : $($_.Exception.Message)" }
  }
}
if (Test-Path -LiteralPath (Join-Path $Here 'WebView2Loader.dll')) { Write-WhickLog 'native loader present' }
else { Write-WhickLog 'native loader MISSING' }

try {
  $wv = New-Object Microsoft.Web.WebView2.WinForms.WebView2
} catch {
  Write-WhickLog "WebView2 SDK missing ($($_.Exception.Message)) — fallback legacy WinForms"
  Remove-Item Env:\WHICK_USB_CORE_ONLY -ErrorAction SilentlyContinue
  & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Here "Whick-USB-Maker.ps1")
  exit 0
}

$wv.Dock = "Fill"
[void]$form.Controls.Add($wv)
$udf = Join-Path $Here ".wv2-profile"
$env:WEBVIEW2_USER_DATA_FOLDER = $udf

# 초기화 완료/실패 진단 (빈 창 무음 방지)
$wv.add_CoreWebView2InitializationCompleted({
  param($sender, $e)
  if ($e.IsSuccess) {
    Write-WhickLog ("WebView2 initialized OK (proc {0}-bit)" -f (@{ $true=64; $false=32 }[[Environment]::Is64BitProcess]))
    try { $sender.CoreWebView2.Settings.AreDefaultContextMenusEnabled = $false } catch { }
  } else {
    Write-WhickLog ("WebView2 init FAILED: " + $e.InitializationException.Message)
    [System.Windows.Forms.MessageBox]::Show("WebView2 init failed: " + $e.InitializationException.Message, "Whick USB Maker") | Out-Null
    $form.Close()
  }
})
$wv.add_NavigationCompleted({
  param($sender, $e)
  if (-not $e.IsSuccess) { Write-WhickLog ("nav failed: " + ($e.WebErrorStatus)) }
  else { Write-WhickLog "nav completed OK" }
})

$wv.add_WebMessageReceived({
  param($sender, $e)
  try {
    $msg = $e.WebMessageAsJson | ConvertFrom-Json
    switch ($msg.cmd) {
      "get-state" {
        Send-Ui @{ type = "state"; ui_culture = (Get-UICulture).Name }
      }
      "list-usb" {
        if (-not $sync.Busy) { Send-Ui (Get-UsbList) }
      }
      "write-usb" {
        if ($sync.Busy) { return }
        $iso = Get-WhickIsoPath
        if (-not $iso) {
          Send-Ui @{ type = "write-error"; message_ko = "ISO 파일을 찾을 수 없습니다. 압축을 다시 풀어 주세요."; message_en = "ISO file not found. Please re-extract the zip." }
          return
        }
        $sync.Busy = $true
        $dn = [int]$msg.disk
        $ps = [powershell]::Create()
        [void]$ps.AddScript($writeScript).AddArgument($sync).AddArgument($dn).AddArgument($iso).AddArgument($LogPath).AddArgument((Join-Path $Here 'Whick-USB-Maker.ps1'))
        [void]$ps.BeginInvoke()
        Write-WhickLog "write dispatched disk=$dn"
      }
      "exit-app" {
        $form.Close()
      }
    }
  } catch {
    Write-WhickLog "message error: $($_.Exception.Message)"
  }
})

# UI 타이머 — 큐 소비해서 WebView로 전송
$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 120
$timer.Add_Tick({
  try {
    while ($sync.Messages.Count -gt 0) {
      if ($null -eq $wv.CoreWebView2) { break }  # 아직 초기화 전 — HTML 주기 갱신이 재요청
      $m = $sync.Messages.Dequeue()
      $json = $m | ConvertTo-Json -Compress -Depth 4
      try { $wv.CoreWebView2.PostWebMessageAsJson($json) } catch { Write-WhickLog "post fail: $($_.Exception.Message)" }
    }
  } catch { }
})
$timer.Start()

# HTML 로드 — 먼저 폼을 보여준 뒤 초기화·로드를 진행 (비동기 완료가 ShowDialog 메시지 펌프 필요)
$form.Add_Shown({
  try {
    Write-WhickLog "form shown - starting init"
    $task = $wv.EnsureCoreWebView2Async($null)
    while (-not $task.IsCompleted) { [System.Windows.Forms.Application]::DoEvents(); Start-Sleep -Milliseconds 30 }
    Write-WhickLog "EnsureCoreWebView2Async done"
    $wv.Source = New-Object System.Uri($AppHtml)
  } catch {
    Write-WhickLog ("init error: " + $_.Exception.Message)
    try { [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, "Whick USB Maker") | Out-Null } catch { }
    $form.Close()
  }
})
[void]$form.ShowDialog()
$timer.Stop()
Write-WhickLog "launcher exit"

} catch {
  Write-WhickLog ("FATAL: " + $_.Exception.GetType().FullName + ": " + $_.Exception.Message)
  try {
    Add-Type -AssemblyName System.Windows.Forms
    [void][System.Windows.Forms.MessageBox]::Show($_.Exception.Message, "Whick USB Maker", [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Error)
  } catch { }
  exit 1
}
