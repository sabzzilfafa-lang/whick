# Setup.bat E2E: 새 Setup.bat을 사용자 실제 DEST 상태에서 실행 (자동 응답)
$dest = "$env:LOCALAPPDATA\SunoHelper"
Write-Host "== before =="
Get-ChildItem $dest | Select-Object -ExpandProperty Name

# 새 Setup.bat 다운로드 (사용자가 받을 것과 동일한 파일)
$setup = "$env:TEMP\SunoHelper-Setup-test.bat"
Invoke-WebRequest "https://whick.org/dl/suno-helper/Setup.bat" -OutFile $setup -UseBasicParsing
Write-Host "setup bytes: $((Get-Item $setup).Length), flatten: $((Select-String -Path $setup -Pattern 'robocopy' -Quiet))"

# 실행 (install.bat의 pause를 통과하기 위해 키 입력 자동화)
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = "cmd.exe"
$psi.Arguments = "/c `"`"$setup`" < NUL`""
$psi.RedirectStandardOutput = $true
$psi.RedirectStandardInput = $false
$psi.UseShellExecute = $false
$p = [System.Diagnostics.Process]::Start($psi)
$out = $p.StandardOutput.ReadToEndAsync()
if (-not $p.WaitForExit(120000)) { $p.Kill(); Write-Host "TIMEOUT" }
Write-Host "== exit: $($p.ExitCode) =="
$out.Result | Select-Object -Last 25
Write-Host "== after: install.bat at root? =="
Test-Path "$dest\install.bat"
Get-ChildItem $dest | Select-Object -ExpandProperty Name
