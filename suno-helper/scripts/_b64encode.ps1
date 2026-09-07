# b64 원본 생성 시점에 이미 깨짐 — Out-File ascii는 b64엔 무해하나 GetBytes 단계가 문제.
# 파일을 통째로 b64로 (텍스트 read 없이 바이트로)
$sectionBytes = [System.IO.File]::ReadAllBytes("c:\Users\user\suno_helper\installer\web\account_suno_section.html")
$jsBytes = [System.IO.File]::ReadAllBytes("c:\Users\user\suno_helper\installer\web\account_suno_script.js")
$sb = [Convert]::ToBase64String($sectionBytes)
$jb = [Convert]::ToBase64String($jsBytes)
$payload = "SECTION_B64=$sb`nJS_B64=$jb`n"
[System.IO.File]::WriteAllText("$env:TEMP\payload.sh", $payload, (New-Object System.Text.UTF8Encoding($false)))
# 로컬 검증
$check = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($sb))
"local verify korean: $($check.Contains([Text.Encoding]::UTF8.GetString([Text.Encoding]::UTF8.GetBytes([char]0xB0 + [string][char]0xB4))))"
$ok = $check.Contains([Text.Encoding]::UTF8.GetString([Text.Encoding]::UTF8.GetBytes("내")))
"local verify 내: $ok"
"payload written: $($sb.Length), $($jb.Length)"
