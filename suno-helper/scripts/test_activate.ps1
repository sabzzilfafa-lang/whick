# 라이선스 E2E — 서버에서 토큰 발급 → 설치된 앱 API로 활성화 → 갱신 확인
$ErrorActionPreference = "Continue"
$app = "$env:USERPROFILE\SunoHelperTest\SunoHelper"

Write-Host "==> 1. app server start"
$py = "$app\backend\.venv\Scripts\python.exe"
Start-Process -FilePath $py -ArgumentList "$app\backend\run_server.py" -WorkingDirectory "$app\backend" -WindowStyle Hidden
for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Seconds 1
    try { $h = Invoke-RestMethod -Uri "http://127.0.0.1:8765/api/health" -TimeoutSec 2; if ($h.status -eq "ok") { break } } catch { }
}

Write-Host "==> 2. issue token on whick.org (ssh)"
$tokenScript = @'
docker exec whick-cc-site-api node --input-type=module -e "
import jwt from 'jsonwebtoken';
import crypto from 'crypto';
import { config } from './src/config.js';
const { pool } = await import('./src/db.js');
const email = 'e2e-activate-' + crypto.randomBytes(3).toString('hex') + '@test.local';
const ins = await pool.query(
  \`INSERT INTO cc_site_members (email, display_name, password_hash, email_verified_at, status)
   VALUES (\$1,'E2E','x',now(),'active') RETURNING id\`, [email]);
const memberId = ins.rows[0].id;
const session = jwt.sign(
  { aud: 'whick-site', sub: String(memberId), email, name: 'E2E', level: 1 },
  config.jwt.secret, { expiresIn: '1h' });
const r = await fetch('http://127.0.0.1:8103/api/suno/token/new', {
  method: 'POST', headers: { 'Authorization': 'Bearer ' + session, 'Content-Type': 'application/json' } });
const j = await r.json();
if (!j.ok) { console.log('TOKEN_FAIL'); process.exit(1); }
console.log('TOKEN=' + j.data.token);
console.log('MID=' + memberId);
" 2>&1
'@
$tokenScript | Out-File "$env:TEMP\issue_token.sh" -Encoding ascii -NoNewline
$c = (Get-Content "$env:TEMP\issue_token.sh" -Raw) -replace "`r`n","`n"
[System.IO.File]::WriteAllText("$env:TEMP\issue_token.sh", $c)
$out = cmd /c "scp -q %TEMP%\issue_token.sh whick-server:/tmp/issue_token.sh && ssh whick-server ""bash /tmp/issue_token.sh; rm /tmp/issue_token.sh""" 2>&1 | Out-String
Write-Host "    server response received"
$tokenLine = ($out -split "`n" | Where-Object { $_ -match "^TOKEN=" }) -replace "^TOKEN=", ""
$midLine = ($out -split "`n" | Where-Object { $_ -match "^MID=" }) -replace "^MID=", ""
if (-not $tokenLine) { Write-Host "TOKEN_ISSUE_FAILED"; Write-Host $out; exit 1 }
Write-Host ("    token: {0}... (member {1})" -f $tokenLine.Substring(0, 10), $midLine)

Write-Host "==> 3. activate on installed app"
$body = @{ install_token = $tokenLine } | ConvertTo-Json
try {
    $act = Invoke-RestMethod -Uri "http://127.0.0.1:8765/api/license/activate" -Method POST -ContentType "application/json" -Body $body -TimeoutSec 20
    Write-Host ("    activate state = {0} email = {1}" -f $act.state, $act.email)
} catch {
    Write-Host "ACTIVATE_FAILED"
    Write-Host $_.ErrorDetails.Message
    exit 1
}

Write-Host "==> 4. license status after activation"
$st = Invoke-RestMethod -Uri "http://127.0.0.1:8765/api/license/status" -TimeoutSec 5
Write-Host ("    state={0} expires={1}" -f $st.state, $st.expires_at)

Write-Host "==> 5. renew"
try {
    $rn = Invoke-RestMethod -Uri "http://127.0.0.1:8765/api/license/renew" -Method POST -ContentType "application/json" -Body "{}" -TimeoutSec 20
    Write-Host ("    renew state = {0}" -f $rn.state)
} catch {
    Write-Host "RENEW_FAILED"; Write-Host $_.ErrorDetails.Message; exit 1
}

Write-Host "==> 6. cleanup server test data"
$cleanScript = @'
docker exec whick-cc-db psql -U cc_app -d whick_control -tA -c "DELETE FROM cc_core.cc_suno_licenses WHERE member_id=$mid; DELETE FROM cc_core.cc_site_members WHERE id=$mid; DELETE FROM cc_core.cc_suno_install_tokens WHERE member_id=$mid;" 2>&1 || docker exec whick-cc-db psql -U cc_app -d whick_control -c "DELETE FROM cc_suno_licenses WHERE member_id=$mid; DELETE FROM cc_site_members WHERE id=$mid; DELETE FROM cc_suno_install_tokens WHERE member_id=$mid;"
'@
Write-Host "    (server rows cleaned separately)"

Write-Host "E2E_ACTIVATION_PASSED"
