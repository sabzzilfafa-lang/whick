# 격리 설치 테스트 — 사용자 디렉터리에 클린 설치 후 정상 동작 확인
$ErrorActionPreference = "Continue"

$testRoot = "$env:USERPROFILE\SunoHelperTest"
if (Test-Path $testRoot) {
    Write-Host "==> 기존 테스트 설치 정리"
    if (Test-Path "$testRoot\SunoHelper\stop.bat") {
        Push-Location "$testRoot\SunoHelper"
        & cmd /c "stop.bat" 2>$null | Out-Null
        Pop-Location
    }
    Start-Sleep -Seconds 2
    Remove-Item $testRoot -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host "==> 1. 압축 해제 (클린 설치)"
New-Item -ItemType Directory -Path $testRoot -Force | Out-Null
Expand-Archive -Path "c:\Users\user\suno_helper\dist_package\SunoHelper-Setup-v1.0.0.zip" -DestinationPath $testRoot -Force
Write-Host "    해제 완료"

Write-Host "==> 2. pip 설치 직접 실행 (install.bat과 동일 단계)"
$venvPython = "$testRoot\SunoHelper\backend\.venv\Scripts\python.exe"
& python -m venv "$testRoot\SunoHelper\backend\.venv"
if ($LASTEXITCODE -ne 0) { Write-Host "VENV_FAILED"; exit 1 }
Write-Host "    venv 생성 완료"

& $venvPython -m pip install -r "$testRoot\SunoHelper\backend\requirements.txt" -q --no-input 2>&1 | Select-Object -Last 3
if ($LASTEXITCODE -ne 0) { Write-Host "PIP_FAILED"; exit 1 }
Write-Host "    PIP_OK"

Write-Host "==> 3. 데이터 폴더/.env 생성"
New-Item -ItemType Directory -Path "$testRoot\SunoHelper\data\uploads" -Force | Out-Null
New-Item -ItemType Directory -Path "$testRoot\SunoHelper\data\logs" -Force | Out-Null
Copy-Item "$testRoot\SunoHelper\.env.example" "$testRoot\SunoHelper\.env" -ErrorAction SilentlyContinue

Write-Host "TEST_INSTALL_DONE"
