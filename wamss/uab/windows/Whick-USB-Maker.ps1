#Requires -Version 5.1
<#
  Whick USB 부팅 디스크 — VIP Room 고객용 단계 안내 (Windows)
  1) USB 꽂기  2) 삭제 경고+동의  3) 제작  4) 완료 → 미니PC USB 부팅

  SSOT ISO: whick-os-live-wired.iso / whick-os-live-wireless.iso (Ubuntu 26.04)
  레거시 alpine-live.iso 는 fallback 만.
  docs/WHICK-OS.md
#>
param(
  [string]$UsbDrive = "",
  [switch]$SkipConfirm,
  [switch]$NoGui
)

$ErrorActionPreference = "Stop"
$Here = $null
try { $Here = Split-Path -Parent $MyInvocation.MyCommand.Path } catch { $Here = $null }
if ([string]::IsNullOrWhiteSpace($Here)) {
  try { $Here = Split-Path -Parent (Get-Process -Id $PID).Path } catch { $Here = $null }
}
if ([string]::IsNullOrWhiteSpace($Here)) { $Here = (Get-Location).Path }
$LogPath = Join-Path $Here "Whick-USB-Maker.log"

function Write-WhickLog {
  param([string]$Message)
  $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $Message"
  try { Add-Content -LiteralPath $LogPath -Value $line -Encoding UTF8 } catch { }
}

function Clear-WhickDownloadMark {
  param([string]$Root)
  if (-not $Root -or -not (Test-Path -LiteralPath $Root)) { return }
  Write-WhickLog "clear download mark: $Root"
  $targets = @($Root)
  try { $targets += (Get-Item -LiteralPath $PSCommandPath).FullName } catch { }
  foreach ($item in $targets) {
    if (-not (Test-Path -LiteralPath $item)) { continue }
    Get-ChildItem -LiteralPath $item -Recurse -Force -ErrorAction SilentlyContinue | ForEach-Object {
      try { Unblock-File -LiteralPath $_.FullName -ErrorAction SilentlyContinue } catch { }
      try {
        $zone = "$($_.FullName):Zone.Identifier"
        if (Test-Path -LiteralPath $zone) {
          Remove-Item -LiteralPath $zone -Force -ErrorAction SilentlyContinue
        }
      } catch { }
    }
    try { Unblock-File -LiteralPath $item -ErrorAction SilentlyContinue } catch { }
  }
}

function Test-WhickAdmin {
  $principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
  return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Request-WhickAdmin {
  if (Test-WhickAdmin) { return }
  $psArgs = @(
    '-NoProfile', '-ExecutionPolicy', 'Bypass', '-WindowStyle', 'Hidden', '-Sta',
    '-File', "`"$PSCommandPath`""
  )
  if ($UsbDrive) { $psArgs += @('-UsbDrive', $UsbDrive) }
  if ($SkipConfirm) { $psArgs += '-SkipConfirm' }
  if ($NoGui) { $psArgs += '-NoGui' }
  try {
    Start-Process -FilePath 'powershell.exe' -Verb RunAs -WindowStyle Hidden -ArgumentList $psArgs | Out-Null
  } catch {
    Show-WhickFatal "관리자 권한이 거부되었거나 UAC를 실행할 수 없습니다.`n`nusb만들기.bat 을 마우스 우클릭 → 관리자 권한으로 실행해 주세요."
    exit 1
  }
  exit 0
}

# raw device open — .NET FileStream은 \\.\ 장치를 못 열므로 Win32 CreateFile P/Invoke 사용
if (-not ('Whick.Native.RawDisk' -as [type])) {
  Add-Type -Namespace Whick.Native -Name RawDisk -MemberDefinition @'
[DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
public static extern IntPtr CreateFileW(
  string lpFileName,
  uint dwDesiredAccess,
  uint dwShareMode,
  IntPtr lpSecurityAttributes,
  uint dwCreationDisposition,
  uint dwFlagsAndAttributes,
  IntPtr hTemplateFile);
[DllImport("kernel32.dll", SetLastError = true)]
public static extern bool CloseHandle(IntPtr hObject);
'@
}
function Open-WhickRawDevice {
  # GENERIC_READ(0x80000000) | GENERIC_WRITE(0x40000000), SHARE_RW(3), OPEN_EXISTING(3), FILE_ATTRIBUTE_NORMAL(0x80)
  $access = [uint32]'2147483648' -bor [uint32]'1073741824'   # GENERIC_READ | GENERIC_WRITE
  $h = [Whick.Native.RawDisk]::CreateFileW(
    $args[0], $access, [uint32]3, [IntPtr]::Zero, [uint32]3, [uint32]128, [IntPtr]::Zero)
  if ($h -eq [IntPtr]::new(-1) -or $h -eq [IntPtr]::Zero) {
    throw "raw device open failed (Win32 error $([System.Runtime.InteropServices.Marshal]::GetLastWin32Error()))"
  }
  return $h
}

function Write-WhickIsoToPhysicalDrive {
  <#
    Whick OS Live ISO 를 USB PhysicalDrive 에 바이트 단위로 기록 (isohybrid DD).
  #>
  param(
    [int]$DiskNum,
    [string]$IsoPath,
    [scriptblock]$OnProgress
  )
  if (-not (Test-Path -LiteralPath $IsoPath)) {
    throw "ISO 없음: $IsoPath"
  }
  $isoItem = Get-Item -LiteralPath $IsoPath
  $isoLen = [int64]$isoItem.Length
  if ($isoLen -lt 10MB) { throw "ISO 파일이 너무 작습니다: $isoLen bytes" }

  $disk = Get-Disk -Number $DiskNum -ErrorAction Stop
  if ($disk.BusType -ne 'USB') { throw "USB 디스크만 선택할 수 있습니다." }
  if ([int64]$disk.Size -lt ($isoLen + 64MB)) {
    $needGb = [math]::Round(($isoLen + 64MB) / 1GB, 1)
    $haveGb = [math]::Round($disk.Size / 1GB, 1)
    throw "USB 용량이 부족합니다.`n필요 약 ${needGb} GB · USB ${haveGb} GB"
  }

  & $OnProgress "USB 파티션을 정리하는 중..." 8
  Write-WhickLog "ISO-DD start disk=$DiskNum iso=$IsoPath size=$isoLen"
  try {
    Get-Disk -Number $DiskNum | Get-Partition -ErrorAction SilentlyContinue | ForEach-Object {
      try { Remove-Partition -DiskNumber $DiskNum -PartitionNumber $_.PartitionNumber -Confirm:$false -ErrorAction Stop } catch {
        Write-WhickLog "Remove-Partition warn: $($_.Exception.Message)"
      }
    }
  } catch {
    Write-WhickLog "partition cleanup: $($_.Exception.Message)"
  }
  try {
    Clear-Disk -Number $DiskNum -RemoveData -RemoveOEM -Confirm:$false -ErrorAction Stop
  } catch {
    Write-WhickLog "Clear-Disk: $($_.Exception.Message)"
  }
  try { Set-Disk -Number $DiskNum -IsOffline $true -ErrorAction Stop } catch {
    Write-WhickLog "Set-Disk offline: $($_.Exception.Message)"
  }
  Start-Sleep -Seconds 1
  Sync-StorageCache

  $destPath = "\\.\PhysicalDrive$DiskNum"
  $bufSize = 4 * 1024 * 1024
  $src = $null
  $dst = $null
  try {
    & $OnProgress "ISO를 USB에 기록하는 중... (0%)" 10
    $src = [System.IO.File]::Open($IsoPath, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::Read)
    $rawHandle = Open-WhickRawDevice $destPath
    $safe = New-Object Microsoft.Win32.SafeHandles.SafeFileHandle($rawHandle, $true)
    $dst = New-Object System.IO.FileStream($safe, [System.IO.FileAccess]::ReadWrite, $bufSize)
    $buf = New-Object byte[] $bufSize
    $written = [int64]0
    $lastPct = -1
    while (($n = $src.Read($buf, 0, $buf.Length)) -gt 0) {
      $dst.Write($buf, 0, $n)
      $written += $n
      $pct = 10 + [int](($written * 85) / $isoLen)
      if ($pct -gt 95) { $pct = 95 }
      if ($pct -ne $lastPct) {
        $lastPct = $pct
        $mb = [math]::Round($written / 1MB, 0)
        $totalMb = [math]::Round($isoLen / 1MB, 0)
        & $OnProgress "ISO 기록 중... $mb / $totalMb MB" $pct
      }
    }
    $dst.Flush($true)
    if ($written -ne $isoLen) {
      throw "ISO 기록 크기 불일치: wrote=$written expected=$isoLen"
    }
    Write-WhickLog "ISO-DD wrote $written bytes to $destPath"
  } finally {
    if ($dst) { try { $dst.Close() } catch { } }
    if ($src) { try { $src.Close() } catch { } }
  }

  & $OnProgress "USB를 다시 인식하는 중..." 97
  try { Set-Disk -Number $DiskNum -IsOffline $false -ErrorAction SilentlyContinue } catch { }
  try { Update-Disk -Number $DiskNum -ErrorAction SilentlyContinue } catch { }
  Sync-StorageCache
  Start-Sleep -Seconds 2
}

function Show-WhickFatal {
  param([string]$Message)
  Write-WhickLog "FATAL: $Message"
  try {
    Add-Type -AssemblyName System.Windows.Forms -ErrorAction Stop
    [System.Windows.Forms.MessageBox]::Show(
      "$Message`n`n자세한 내용: $LogPath",
      "Whick USB Maker",
      [System.Windows.Forms.MessageBoxButtons]::OK,
      [System.Windows.Forms.MessageBoxIcon]::Error
    ) | Out-Null
  } catch {
    Write-Host ""
    Write-Host "ERROR: $Message" -ForegroundColor Red
    Write-Host "로그: $LogPath"
    Read-Host "Enter 키로 종료"
  }
}

function Get-WhickPaths {
  # 무선 맞춤 zip 폴더에 예전에 풀어 둔 유선 ISO가 남아 있으면 유선이 먼저 잡혀
  # SSID 없는 무선 화면처럼 보이거나 잘못된 매체가 구워질 수 있음 → wireless 우선.
  $candidates = @(
    (Join-Path $Here "whick-os-live-wireless.iso"),
    (Join-Path $Here "whick-os-live-wired.iso"),
    (Join-Path $Here "alpine-live.iso"),
    (Join-Path $Here "alpine-virt.iso")
  )
  $iso = $null
  foreach ($c in $candidates) {
    if (Test-Path -LiteralPath $c) { $iso = $c; break }
  }
  if (-not $iso) {
    throw "Whick OS Live ISO 없음: $Here`nwhick-os-live-wired.iso (또는 wireless) 를 같은 폴더에 두고 다시 실행하세요."
  }
  Write-WhickLog "ISO selected: $iso"
  $shaFile = "$iso.sha256"
  return @{
    AlpineIso = $iso
    AlpineName = Split-Path -Leaf $iso
    AlpineShaFile = $shaFile
  }
}

function Get-UsbDisks {
  Get-Disk | Where-Object { $_.BusType -eq 'USB' -and $_.Size -gt 3GB } |
    Sort-Object Number
}

function Sync-StorageCache {
  try { Update-HostStorageCache -ErrorAction SilentlyContinue | Out-Null } catch { }
  Start-Sleep -Milliseconds 500
}

function Get-PartitionsForDisk {
  param([int]$DiskNum)
  Get-Partition -DiskNumber $DiskNum -ErrorAction SilentlyContinue
}

function Get-VentoyDriveLetter {
  param(
    [int]$DiskNum,
    [string]$DiskUniqueId = ""
  )

  $parts = Get-PartitionsForDisk -DiskNum $DiskNum
  foreach ($p in $parts) {
    $v = Get-Volume -Partition $p -ErrorAction SilentlyContinue
    if ($v -and $v.DriveLetter -and $v.FileSystemLabel -like "*Ventoy*") {
      return $v.DriveLetter
    }
  }

  foreach ($p in $parts) {
    $v = Get-Volume -Partition $p -ErrorAction SilentlyContinue
    if ($v -and $v.DriveLetter -and $v.FileSystem -in @("exFAT", "FAT", "FAT32", "NTFS")) {
      return $v.DriveLetter
    }
  }

  if ($DiskUniqueId) {
    $disk = Get-Disk | Where-Object { $_.UniqueId -eq $DiskUniqueId -and $_.BusType -eq "USB" } | Select-Object -First 1
    if ($disk -and $disk.Number -ne $DiskNum) {
      foreach ($p in Get-PartitionsForDisk -DiskNum $disk.Number) {
        $v = Get-Volume -Partition $p -ErrorAction SilentlyContinue
        if ($v -and $v.DriveLetter) { return $v.DriveLetter }
      }
    }
  }

  foreach ($v in Get-Volume -ErrorAction SilentlyContinue) {
    if ($v.DriveLetter -and $v.FileSystemLabel -like "*Ventoy*") {
      return $v.DriveLetter
    }
  }

  return $null
}

function Wait-VentoyDriveLetter {
  param(
    [int]$DiskNum,
    [string]$DiskUniqueId = "",
    [scriptblock]$ProgressCallback = $null,
    [int]$TimeoutSec = 120
  )

  $deadline = (Get-Date).AddSeconds($TimeoutSec)
  $attempt = 0
  while ((Get-Date) -lt $deadline) {
    $attempt++
    Sync-StorageCache
    if ($ProgressCallback -and ($attempt -eq 1 -or ($attempt % 5) -eq 0)) {
      & $ProgressCallback "Ventoy USB를 인식하는 중... ($attempt)"
    }
    $letter = Get-VentoyDriveLetter -DiskNum $DiskNum -DiskUniqueId $DiskUniqueId
    if ($letter) { return $letter }
    Start-Sleep -Seconds 2
  }
  return $null
}

function Get-WhickExpectedSha256 {
  param([string]$FileName)
  $sidecar = Join-Path $Here "$FileName.sha256"
  if (-not (Test-Path -LiteralPath $sidecar)) { return $null }
  $line = (Get-Content -LiteralPath $sidecar -TotalCount 1 -ErrorAction SilentlyContinue)
  if (-not $line) { return $null }
  return ($line.Trim().Split(" ")[0]).ToLower()
}

function Get-WhickUsbDestRoot {
  param(
    [int]$DiskNum,
    [string]$DiskUniqueId = ""
  )

  Sync-StorageCache
  $letter = Get-VentoyDriveLetter -DiskNum $DiskNum -DiskUniqueId $DiskUniqueId
  if (-not $letter) {
    throw "Ventoy USB 드라이브를 찾지 못했습니다.`nUSB 연결·전원을 확인한 뒤 다시 시도하세요."
  }

  $root = "${letter}:\"
  if (-not (Test-Path -LiteralPath $root)) {
    throw "USB 드라이브 ${letter}: 를 열 수 없습니다.`nUSB를 다시 꽂은 뒤 [USB 만들기]를 다시 시도하세요."
  }

  try {
    $vol = Get-Volume -DriveLetter $letter -ErrorAction Stop
    if ($vol -and $vol.DriveType -ne "Removable" -and $vol.FileSystemLabel -notlike "*Ventoy*") {
      Write-WhickLog "warn dest ${letter}: DriveType=$($vol.DriveType) label=$($vol.FileSystemLabel)"
    }
  } catch {
    Write-WhickLog "volume info skipped: $($_.Exception.Message)"
  }

  return @{
    Letter = $letter
    Root   = $root
  }
}

function Test-WhickUsbFreeSpace {
  param(
    [string]$Root,
    [long]$RequiredBytes
  )

  $driveName = $Root.TrimEnd('\')
  if ($driveName.Length -lt 2) { return }
  $psDrive = Get-PSDrive -Name $driveName[0] -ErrorAction SilentlyContinue
  if (-not $psDrive) { return }
  $free = [long]$psDrive.Free
  $need = $RequiredBytes + 64MB
  if ($free -lt $need) {
    $freeGb = [math]::Round($free / 1GB, 2)
    $needGb = [math]::Round($need / 1GB, 2)
    throw "USB 여유 공간이 부족합니다.`n필요 약 ${needGb} GB · 사용 가능 ${freeGb} GB`n8GB 이상 USB를 사용하세요."
  }
}

function Copy-WhickFileWithRobocopy {
  param(
    [string]$Src,
    [string]$Dst,
    [scriptblock]$OnBytesAdded = $null
  )

  $srcItem = Get-Item -LiteralPath $Src
  $srcDir = $srcItem.DirectoryName
  $srcName = $srcItem.Name
  $dstDir = Split-Path -Parent $Dst
  if (-not $dstDir) { $dstDir = (Split-Path -Parent $Dst.TrimEnd('\')) }
  if ($dstDir -and -not (Test-Path -LiteralPath $dstDir)) {
    New-Item -ItemType Directory -Force -Path $dstDir | Out-Null
  }
  if (-not $dstDir.EndsWith('\')) { $dstDir = "$dstDir\" }

  $robocopy = Join-Path $env:SystemRoot "System32\robocopy.exe"
  if (-not (Test-Path -LiteralPath $robocopy)) {
    throw "robocopy.exe 없음"
  }

  if (Test-Path -LiteralPath $Dst) {
    Remove-Item -LiteralPath $Dst -Force -ErrorAction SilentlyContinue
  }

  $before = 0L
  $args = @(
    $srcDir, $dstDir, $srcName,
    "/R:3", "/W:2", "/NP", "/NFL", "/NDL", "/NJH", "/NJS", "/BYTES"
  )
  Write-WhickLog "robocopy $($args -join ' ')"
  $proc = Start-Process -FilePath $robocopy -ArgumentList $args -PassThru -WindowStyle Hidden
  $last = 0L
  while (-not $proc.HasExited) {
    Start-Sleep -Milliseconds 400
    if ($OnBytesAdded -and (Test-Path -LiteralPath $Dst)) {
      $cur = (Get-Item -LiteralPath $Dst).Length
      if ($cur -gt $last) {
        & $OnBytesAdded ($cur - $last)
        $last = $cur
      }
    }
  }
  $code = $proc.ExitCode
  if ($code -ge 8) {
    throw "robocopy exit $code"
  }

  if (-not (Test-Path -LiteralPath $Dst)) {
    throw "robocopy missing dest: $srcName"
  }
  $after = (Get-Item -LiteralPath $Dst).Length
  if ($OnBytesAdded -and $after -gt $before) {
    & $OnBytesAdded ($after - $before)
  }
}

function Copy-WhickFileStream {
  param(
    [string]$Src,
    [string]$Dst,
    [scriptblock]$OnBytesAdded = $null,
    [scriptblock]$ResolveDest = $null,
    [long]$ResumeFrom = 0
  )

  $srcItem = Get-Item -LiteralPath $Src
  $total = [int64]$srcItem.Length
  $copied = [int64][Math]::Max(0, $ResumeFrom)
  $bufferSize = 1MB
  $buffer = New-Object byte[] $bufferSize
  $srcStream = [System.IO.File]::OpenRead($srcItem.FullName)
  $dstStream = [System.IO.File]::Open(
    $Dst,
    [System.IO.FileMode]::OpenOrCreate,
    [System.IO.FileAccess]::Write,
    [System.IO.FileShare]::None
  )
  try {
    if ($copied -gt 0) {
      $srcStream.Seek($copied, [System.IO.SeekOrigin]::Begin) | Out-Null
      $dstStream.Seek($copied, [System.IO.SeekOrigin]::Begin) | Out-Null
      Write-WhickLog "resume $($srcItem.Name) at $copied bytes"
    }
    $checkEvery = 4MB
    $sinceCheck = 0L
    while (($read = $srcStream.Read($buffer, 0, $buffer.Length)) -gt 0) {
      $dstStream.Write($buffer, 0, $read)
      $copied += $read
      $sinceCheck += $read
      if ($OnBytesAdded) { & $OnBytesAdded $read }
      if ($sinceCheck -ge $checkEvery -and $ResolveDest) {
        $sinceCheck = 0L
        $destInfo = & $ResolveDest
        $expectedRoot = $destInfo.Root
        if ($Dst -notlike "$expectedRoot*") {
          throw "USB 드라이브 문자가 변경되었습니다"
        }
        if (-not (Test-Path -LiteralPath $expectedRoot)) {
          throw "USB 드라이브 연결이 끊어졌습니다"
        }
      }
    }
    $dstStream.Flush($true)
  } finally {
    $dstStream.Close()
    $srcStream.Close()
  }
  if ($copied -ne $total) {
    throw "stream size mismatch ($copied / $total)"
  }
}

function Test-WhickUsbIsExfat {
  param([string]$Root)
  $letter = $Root.TrimEnd('\').Substring(0, 1)
  $vol = Get-Volume -DriveLetter $letter -ErrorAction SilentlyContinue
  if (-not $vol) { return $true }
  return $vol.FileSystem -in @('exFAT', 'FAT32', 'FAT')
}

function Copy-WhickFileVerified {
  param(
    [string]$Src,
    [string]$Dst,
    [string]$ExpectedSha256 = "",
    [scriptblock]$OnBytesAdded = $null,
    [scriptblock]$ResolveDest = $null,
    [string]$DstRel = ""
  )

  if (-not (Test-Path -LiteralPath $Src)) { throw "source missing: $Src" }
  $srcItem = Get-Item -LiteralPath $Src
  $total = [int64]$srcItem.Length
  $preferStream = $true
  if ($ResolveDest -and $DstRel) {
    $preferStream = Test-WhickUsbIsExfat -Root (& $ResolveDest).Root
  }

  $maxAttempts = 4
  for ($attempt = 1; $attempt -le $maxAttempts; $attempt++) {
    if ($ResolveDest -and $DstRel) {
      $destInfo = & $ResolveDest
      $Dst = Join-Path $destInfo.Root $DstRel
      $preferStream = Test-WhickUsbIsExfat -Root $destInfo.Root
    }

    $dstDir = Split-Path -Parent $Dst
    if (-not (Test-Path -LiteralPath $dstDir)) {
      New-Item -ItemType Directory -Force -Path $dstDir | Out-Null
    }

    $resumeFrom = 0L
    if (Test-Path -LiteralPath $Dst) {
      $existing = (Get-Item -LiteralPath $Dst).Length
      if ($existing -gt 0 -and $existing -lt $total) {
        $resumeFrom = [int64]$existing
      } elseif ($existing -ge $total) {
        Remove-Item -LiteralPath $Dst -Force -ErrorAction SilentlyContinue
      }
    }

    try {
      if (-not $preferStream -and $total -ge 32MB -and $attempt -eq 1) {
        try {
          Copy-WhickFileWithRobocopy -Src $Src -Dst $Dst -OnBytesAdded $OnBytesAdded
        } catch {
          Write-WhickLog "robocopy fallback to stream: $($_.Exception.Message)"
          if (Test-Path -LiteralPath $Dst) {
            Remove-Item -LiteralPath $Dst -Force -ErrorAction SilentlyContinue
          }
          $resumeFrom = 0L
        }
      }
      if (-not (Test-Path -LiteralPath $Dst) -or (Get-Item -LiteralPath $Dst).Length -ne $total) {
        Copy-WhickFileStream -Src $Src -Dst $Dst -OnBytesAdded $OnBytesAdded -ResolveDest $ResolveDest -ResumeFrom $resumeFrom
        Write-WhickLog "stream copied $($srcItem.Name)"
      }
      break
    } catch {
      $msg = $_.Exception.Message
      Write-WhickLog "copy attempt $attempt failed for $($srcItem.Name): $msg"
      if ($attempt -ge $maxAttempts) { throw }
      if ($msg -notmatch 'does not exist|device|media|disconnected|timeout|sharing violation|robocopy|드라이브|연결|mismatch') {
        throw
      }
      if (Test-Path -LiteralPath $Dst) {
        Remove-Item -LiteralPath $Dst -Force -ErrorAction SilentlyContinue
      }
      Sync-StorageCache
      Start-Sleep -Seconds (2 * $attempt)
    }
  }

  if (-not (Test-Path -LiteralPath $Dst)) { throw "USB copy failed: $($srcItem.Name) not found on USB" }
  $dstLen = (Get-Item -LiteralPath $Dst).Length
  if ($dstLen -ne $total) {
    throw "USB copy size mismatch: $($srcItem.Name) ($dstLen bytes, expected $total)"
  }

  if (-not $ExpectedSha256) { $ExpectedSha256 = Get-WhickExpectedSha256 -FileName $srcItem.Name }
  if ($ExpectedSha256) {
    $hash = (Get-FileHash -LiteralPath $Dst -Algorithm SHA256).Hash.ToLower()
    if ($hash -ne $ExpectedSha256.ToLower()) {
      throw "USB copy checksum failed: $($srcItem.Name)`nexpected $ExpectedSha256`ngot $hash"
    }
    Write-WhickLog "verified $($srcItem.Name) sha256=$hash size=$dstLen"
  } else {
    Write-WhickLog "verified $($srcItem.Name) size=$dstLen"
  }
}

function Get-WhickUsbCopyPlan {
  param(
    [string]$Root,
    [hashtable]$Paths
  )

  $items = New-Object System.Collections.Generic.List[object]
  $addFile = {
    param([string]$Src, [string]$DstRel, [string]$Label)
    if (-not (Test-Path -LiteralPath $Src)) { return }
    $size = (Get-Item -LiteralPath $Src).Length
    $items.Add([pscustomobject]@{
      Src    = $Src
      DstRel = $DstRel
      Label  = $Label
      Size   = $size
    }) | Out-Null
  }

  & $addFile $Paths.AlpineIso $Paths.AlpineName $Paths.AlpineName
  $alpineApk = Join-Path $Root "alpine.apkovl.tar.gz"
  if (-not (Test-Path -LiteralPath $alpineApk)) {
    throw "alpine.apkovl.tar.gz 없음 — Alpine 자동 시작에 필요합니다."
  }
  & $addFile $alpineApk "alpine.apkovl.tar.gz" "alpine.apkovl.tar.gz"
  $bootDir = Join-Path $Root "whick-boot-connect"
  if (Test-Path -LiteralPath $bootDir) {
    Get-ChildItem -LiteralPath $bootDir -Recurse -File | ForEach-Object {
      $rel = $_.FullName.Substring($bootDir.Length).TrimStart('\')
      $items.Add([pscustomobject]@{
        Src    = $_.FullName
        DstRel = Join-Path "whick-boot-connect" $rel
        Label  = "whick-boot-connect\$rel"
        Size   = $_.Length
      }) | Out-Null
    }
  }
  & $addFile (Join-Path $Root "ventoy\ventoy.json") "ventoy\ventoy.json" "ventoy\ventoy.json"
  & $addFile (Join-Path $Root "ventoy\alpine-grub.cfg") "ventoy\alpine-grub.cfg" "ventoy\alpine-grub.cfg"
  & $addFile (Join-Path $Root "ventoy\alpine-syslinux.cfg") "ventoy\alpine-syslinux.cfg" "ventoy\alpine-syslinux.cfg"
  $themeDir = Join-Path $Root "ventoy\theme"
  if (Test-Path -LiteralPath $themeDir) {
    Get-ChildItem -LiteralPath $themeDir -Recurse -File | ForEach-Object {
      $rel = $_.FullName.Substring($themeDir.Length).TrimStart('\')
      $dstRel = Join-Path "ventoy\theme" $rel
      & $addFile $_.FullName $dstRel $dstRel
    }
  }
  return $items
}

function Invoke-WhickProgress {
  param(
    [scriptblock]$Handler,
    [string]$Message,
    [int]$Percent = -1
  )
  if ($Handler) { & $Handler $Message $Percent }
}

function Sync-RemovableVolume {
  param([string]$DriveLetter)
  if (-not $DriveLetter) { return }
  try {
    $path = "\\.\${DriveLetter}:"
    $fs = [System.IO.File]::Open($path, [System.IO.FileMode]::Open, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::ReadWrite)
    $fs.Flush($true)
    $fs.Close()
  } catch {
    Write-WhickLog "volume flush skipped: $($_.Exception.Message)"
  }
}

function Install-WhickUsb {
  param(
    [int]$DiskNum,
    [scriptblock]$OnProgress
  )

  $paths = Get-WhickPaths
  Clear-WhickDownloadMark -Root $Here
  try { Unblock-File -LiteralPath $paths.AlpineIso -ErrorAction SilentlyContinue } catch { }

  & $OnProgress "USB를 준비하는 중... (기존 데이터 삭제)" 5
  Sync-StorageCache
  Write-WhickIsoToPhysicalDrive -DiskNum $DiskNum -IsoPath $paths.AlpineIso -OnProgress $OnProgress
  & $OnProgress "USB 제작 완료" 100
  return "PhysicalDrive$DiskNum"
}

function Invoke-CliFlow {
  $paths = Get-WhickPaths | Out-Null
  Write-Host "`n=== Whick USB 부팅 디스크 만들기 ===`n" -ForegroundColor Cyan
  Write-Host "1) USB 메모리를 PC에 꽂아 주세요.`n"

  if (-not $UsbDrive) {
    Get-UsbDisks | Format-Table Number, FriendlyName, @{N='GB';E={[math]::Round($_.Size/1GB,1)}} -AutoSize
    $UsbDrive = (Read-Host "USB 디스크 번호 (Disk Number)").Trim()
  }

  if (-not $SkipConfirm) {
    Write-Host "`n경고: 선택한 USB의 모든 파일이 삭제됩니다.`n" -ForegroundColor Red
    if ((Read-Host "계속하시겠습니까? (yes 입력)") -ne "yes") { exit 0 }
  }

  $dest = Install-WhickUsb -DiskNum ([int]$UsbDrive) -OnProgress { param($m, [int]$p = -1) Write-Host "  $m" }
  Write-Host "`n완료되었습니다.`nUSB: $dest" -ForegroundColor Green
  Write-Host "다음: 미니PC USB 부팅 (유선 권장 / 무선은 스마트폰 Wi-Fi 설정)`n"
}

function Show-WhickWizard {
  Add-Type -AssemblyName System.Windows.Forms
  Add-Type -AssemblyName System.Drawing

  try { Get-WhickPaths | Out-Null } catch {
    Show-WhickFatal $_.Exception.Message
    return
  }

  $form = New-Object System.Windows.Forms.Form
  $form.Text = "Whick 뮤직서버 - USB 부팅 디스크 만들기"
  $form.Size = New-Object System.Drawing.Size(560, 420)
  $form.StartPosition = "CenterScreen"
  $form.FormBorderStyle = "FixedDialog"
  $form.MaximizeBox = $false
  $form.Font = New-Object System.Drawing.Font("Malgun Gothic", 10)

  $title = New-Object System.Windows.Forms.Label
  $title.Location = New-Object System.Drawing.Point(24, 20)
  $title.Size = New-Object System.Drawing.Size(500, 28)
  $title.Font = New-Object System.Drawing.Font("Malgun Gothic", 13, [System.Drawing.FontStyle]::Bold)
  $title.Text = "Whick USB 부팅 디스크"

  $body = New-Object System.Windows.Forms.Label
  $body.Location = New-Object System.Drawing.Point(24, 58)
  $body.Size = New-Object System.Drawing.Size(500, 180)
  $body.Text = ""

  $usbCombo = New-Object System.Windows.Forms.ComboBox
  $usbCombo.Location = New-Object System.Drawing.Point(24, 248)
  $usbCombo.Size = New-Object System.Drawing.Size(500, 28)
  $usbCombo.DropDownStyle = "DropDownList"
  $usbCombo.Visible = $false

  $refreshBtn = New-Object System.Windows.Forms.Button
  $refreshBtn.Location = New-Object System.Drawing.Point(24, 282)
  $refreshBtn.Size = New-Object System.Drawing.Size(120, 32)
  $refreshBtn.Text = "USB 새로고침"
  $refreshBtn.Visible = $false

  $agreeCheck = New-Object System.Windows.Forms.CheckBox
  $agreeCheck.Location = New-Object System.Drawing.Point(24, 248)
  $agreeCheck.Size = New-Object System.Drawing.Size(500, 24)
  $agreeCheck.Text = "USB의 모든 파일이 삭제됨을 이해했으며, 진행합니다."
  $agreeCheck.Visible = $false

  $progress = New-Object System.Windows.Forms.ProgressBar
  $progress.Location = New-Object System.Drawing.Point(24, 282)
  $progress.Size = New-Object System.Drawing.Size(500, 22)
  $progress.Style = "Marquee"
  $progress.Visible = $false

  $status = New-Object System.Windows.Forms.Label
  $status.Location = New-Object System.Drawing.Point(24, 310)
  $status.Size = New-Object System.Drawing.Size(500, 24)
  $status.ForeColor = [System.Drawing.Color]::DimGray
  $status.Text = ""

  $prevBtn = New-Object System.Windows.Forms.Button
  $prevBtn.Location = New-Object System.Drawing.Point(24, 340)
  $prevBtn.Size = New-Object System.Drawing.Size(100, 34)
  $prevBtn.Text = "이전"
  $prevBtn.Enabled = $false

  $nextBtn = New-Object System.Windows.Forms.Button
  $nextBtn.Location = New-Object System.Drawing.Point(424, 340)
  $nextBtn.Size = New-Object System.Drawing.Size(100, 34)
  $nextBtn.Text = "다음"

  $stepDots = New-Object System.Windows.Forms.Label
  $stepDots.Location = New-Object System.Drawing.Point(200, 346)
  $stepDots.Size = New-Object System.Drawing.Size(160, 24)
  $stepDots.TextAlign = "MiddleCenter"
  $stepDots.ForeColor = [System.Drawing.Color]::Gray

  $script:Step = 0
  $script:UsbMap = @{}

  $usbDetectTimer = New-Object System.Windows.Forms.Timer
  $usbDetectTimer.Interval = 1500

  function Update-Step0UsbGate {
    if ($script:Step -ne 0) { return }
    Sync-StorageCache | Out-Null
    $hasUsb = @(Get-UsbDisks).Count -gt 0
    $nextBtn.Visible = $hasUsb
    $nextBtn.Enabled = $hasUsb
    if (-not $hasUsb) {
      $status.Text = "USB를 꽂아 주세요. (8GB 이상) — 감지되면 [다음]이 표시됩니다."
    } else {
      $status.Text = "USB가 감지되었습니다. [다음]을 눌러 USB를 선택하세요."
    }
  }

  function Update-StepDots {
    $stepDots.Text = "Step $($script:Step + 1) / 5"
  }

  function Refresh-UsbList {
    $usbCombo.Items.Clear()
    $script:UsbMap = @{}
    foreach ($d in Get-UsbDisks) {
      $gb = [math]::Round($d.Size / 1GB, 1)
      $label = "디스크 $($d.Number) - $($d.FriendlyName) ($gb GB)"
      [void]$usbCombo.Items.Add($label)
      $script:UsbMap[$label] = $d.Number
    }
    if ($usbCombo.Items.Count -gt 0) { $usbCombo.SelectedIndex = 0 }
  }

  function Set-Step([int]$n) {
    $script:Step = $n
    Update-StepDots
    if ($n -ne 0) { $usbDetectTimer.Stop() }
    $usbCombo.Visible = $false
    $refreshBtn.Visible = $false
    $agreeCheck.Visible = $false
    $progress.Visible = $false
    $prevBtn.Enabled = ($n -gt 0 -and $n -lt 4)
    $nextBtn.Visible = $true
    $nextBtn.Enabled = $true
    $nextBtn.Text = if ($n -eq 2) { "USB 만들기" } elseif ($n -eq 4) { "닫기" } else { "다음" }

    switch ($n) {
      0 {
        $title.Text = "1단계 - USB 준비"
        $body.Text = @"
Whick VIP Room에서 받은 파일을 압축 해제한 뒤 이 프로그램을 실행하셨습니다.

1) USB 메모리(8GB 이상)를 Windows PC에 꽂아 주세요.
2) USB가 감지되면 [다음] 버튼이 나타납니다.

미니PC는 유선 인터넷 연결을 권장합니다.
(안정적인 연결과 음질)

USB 부팅 후 유선(또는 USB-LAN)을 연결하세요.
무선 VIP USB는 사전 입력한 Wi-Fi에 자동 연결됩니다.
스마트폰은 같은 공유기 Wi-Fi에서 고유 접속 주소로 진행합니다.

중요: 미니PC와 스마트폰은
같은 공유기에 연결되어 있어야 합니다.

설치 과정은 스마트폰 화면에서 확인합니다.
(whick.org 로그인 필수 / 설치 화면을 닫지 마세요)
"@
        $nextBtn.Visible = $false
        $nextBtn.Enabled = $false
        $status.Text = "USB를 꽂아 주세요. (8GB 이상) — 감지되면 [다음]이 표시됩니다."
        $usbDetectTimer.Start()
        Update-Step0UsbGate
      }
      1 {
        $title.Text = "2단계 - USB 선택"
        $body.Text = @"
아래 목록에서 Whick 부팅 디스크로 사용할 USB를 선택하세요.

USB가 보이지 않으면 [USB 새로고침]을 눌러 주세요.
"@
        $usbCombo.Visible = $true
        $refreshBtn.Visible = $true
        Refresh-UsbList
        if ($usbCombo.Items.Count -eq 0) {
          $nextBtn.Enabled = $false
          $status.Text = "USB가 감지되지 않습니다. USB를 꽂은 뒤 [USB 새로고침]을 눌러 주세요."
        } else {
          $status.Text = ""
        }
      }
      2 {
        if ($usbCombo.SelectedItem -eq $null) {
          [System.Windows.Forms.MessageBox]::Show("USB를 선택해 주세요.", "Whick USB Maker") | Out-Null
          $script:Step = 1
          Set-Step 1
          return
        }
        $title.Text = "3단계 - 확인"
        $body.Text = @"
선택한 USB: $($usbCombo.SelectedItem)

[!] 경고
이 USB에 저장된 모든 파일이 삭제됩니다.
Whick 부팅용 USB가 만들어집니다.

아래 확인란에 체크한 뒤 [USB 만들기]를 눌러 주세요.
"@
        $agreeCheck.Visible = $true
        $agreeCheck.Checked = $false
        $nextBtn.Enabled = $false
        $status.Text = ""
      }
      3 {
        $title.Text = "4단계 - USB 제작 중"
        $body.Text = "Whick 부팅 USB를 만드는 중입니다.`n잠시만 기다려 주세요. USB를 빼지 마세요."
        $progress.Style = "Continuous"
        $progress.Minimum = 0
        $progress.Maximum = 100
        $progress.Value = 0
        $progress.Visible = $true
        $prevBtn.Enabled = $false
        $nextBtn.Enabled = $false
        $form.Refresh()

        $diskNum = $script:UsbMap[$usbCombo.SelectedItem]
        try {
          $dest = Install-WhickUsb -DiskNum $diskNum -OnProgress {
            param($Message, [int]$Percent = -1)
            $status.Text = $Message
            if ($Percent -ge 0) {
              $progress.Style = "Continuous"
              $progress.Value = [Math]::Min(100, [Math]::Max(0, $Percent))
            }
            $form.Refresh()
            [System.Windows.Forms.Application]::DoEvents()
          }
          $progress.Visible = $false
          $script:Step = 4
          Set-Step 4
          $script:LastDest = $dest
        } catch {
          $progress.Visible = $false
          $err = $_.Exception.Message
          if ($err -match 'does not exist|device|media|disconnected|드라이브|연결') {
            $err = @"
USB 연결이 끊어졌거나 드라이브를 찾지 못했습니다.

· USB를 PC 본체 포트(허브 말고)에 꽂아 주세요
· 다른 프로그램이 USB를 사용 중이면 닫고 다시 시도해 주세요
· 다른 USB(8GB 이상)로 시도해 보세요

기술 상세: $err
"@
          }
          [System.Windows.Forms.MessageBox]::Show($err, "제작 실패", "OK", "Error") | Out-Null
          Set-Step 2
          $nextBtn.Text = "USB 만들기"
        }
        return
      }
      4 {
        $title.Text = "완료"
        $guidePath = Join-Path $Here "USB-고객안내.txt"
        $legalPath = Join-Path $Here "USB-저작권-배포안내.txt"
        if (Test-Path -LiteralPath $guidePath) {
          $guideText = (Get-Content -LiteralPath $guidePath -Raw -Encoding UTF8).Trim()
          if (Test-Path -LiteralPath $legalPath) {
            $guideText += "`n`n---`n" + (Get-Content -LiteralPath $legalPath -Raw -Encoding UTF8).Trim()
          }
          $body.Text = "[OK] USB 부팅 디스크 제작이 완료되었습니다.`n`n" + $guideText
        } else {
          $body.Text = @"
[OK] USB 부팅 디스크 제작이 완료되었습니다.

설치 안내는 USB-고객안내.txt 를 확인해 주세요.
"@
        }
        $status.Text = if ($script:LastDest) { "USB: $($script:LastDest)" } else { "" }
      }
    }
  }

  $usbDetectTimer.Add_Tick({ Update-Step0UsbGate })
  $refreshBtn.Add_Click({
    Refresh-UsbList
    if ($usbCombo.Items.Count -gt 0) { $nextBtn.Enabled = $true; $status.Text = "" }
    else { $nextBtn.Enabled = $false; $status.Text = "USB가 감지되지 않습니다. USB를 꽂은 뒤 [USB 새로고침]을 눌러 주세요." }
  })
  $agreeCheck.Add_CheckedChanged({ $nextBtn.Enabled = $agreeCheck.Checked })
  $prevBtn.Add_Click({ if ($script:Step -gt 0 -and $script:Step -lt 4) { Set-Step ($script:Step - 1) } })
  $nextBtn.Add_Click({
    if ($script:Step -eq 4) { $form.Close(); return }
    if ($script:Step -eq 2 -and -not $agreeCheck.Checked) {
      [System.Windows.Forms.MessageBox]::Show("확인란에 체크해 주세요.", "Whick USB Maker") | Out-Null
      return
    }
    if ($script:Step -eq 3) { Set-Step 3; return }
    Set-Step ($script:Step + 1)
  })

  $form.Controls.AddRange(@($title, $body, $usbCombo, $refreshBtn, $agreeCheck, $progress, $status, $prevBtn, $nextBtn, $stepDots))
  $form.Add_FormClosed({ $usbDetectTimer.Stop(); $usbDetectTimer.Dispose() })
  Set-Step 0
  [void]$form.ShowDialog()
}

# CORE_ONLY: WebView2 런처가 함수 재사용을 위해 도트 소싱 — GUI 진입 없이 함수만 로드
# (scriptblock 내 도트소싱 시 return이 호출 scriptblock까지 종료시키므로 if 가드 사용)
if ($env:WHICK_USB_CORE_ONLY -ne "1") {

try {
  Request-WhickAdmin
  Clear-WhickDownloadMark -Root $Here
  Write-WhickLog "start pid=$PID admin=$([bool](Test-WhickAdmin)) cwd=$Here"
  if ($NoGui) {
    Invoke-CliFlow
  } else {
    Show-WhickWizard
  }
} catch {
  Show-WhickFatal $_.Exception.Message
  exit 1
}

}  # end CORE_ONLY GUI guard
