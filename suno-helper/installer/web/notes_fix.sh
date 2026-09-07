#!/bin/bash
# 한글 release_notes를 \uXXXX 이스케이프로 교체 (전송 경로 인코딩 무관화)
set -e
NOTES_JSON='\ud55c\uae00 \uac00\uc0ac \uc758\uc5ed(EN\u2192KO) \uc9c0\uc6d0, \ube0c\ub77c\uc6b0\uc800 \ub2eb\ud798 \uc790\ub3d9 \uc885\ub8cc, Intel QSV \uc778\ucf54\ub354 \uc9c0\uc6d0, \uc6f9 \ub300\uc2dc\ubcf4\ub4dc \uc124\uce58\u00b7\uc2e4\ud589(suno-helper://) \ud750\ub984'

# psql: E'' 문자열로 \uXXXX 해석 (PostgreSQL Unicode escape)
docker exec whick-cc-db psql -U cc_app -d whick_control -v ON_ERROR_STOP=1 -c "UPDATE cc_core.cc_software_versions SET release_notes = E'$NOTES_JSON' WHERE version='v0.9.00';"

echo '=== verify: hex 정렬 (UTF-8 바이트 관점) ==='
docker exec whick-cc-db psql -U cc_app -d whick_control -t -c "SELECT release_notes FROM cc_core.cc_software_versions WHERE version='v0.9.00';" > /tmp/notes_out.txt
python3 - <<'PY'
raw = open('/tmp/notes_out.txt','rb').read()
# psql 공백 트림
txt = raw.decode('utf-8', 'replace').strip()
print('DB text :', txt)
print('utf8 ok :', txt.startswith('한글'))
PY

echo '=== version file SSOT도 이스케이프로 정합 ==='
python3 - <<'PY'
import json
p = "/data/whick-ai/2_control_center/config/solutions/suno-helper.json"
notes = "한글 가사 의역(EN→KO) 지원, 브라우저 닫힘 자동 종료, Intel QSV 인코더 지원, 웹 대시보드 설치·실행(suno-helper://) 흐름"
d = {"product":"suno-helper","version":"0.9.00","notes":notes,
     "url":"https://whick.org/dl/suno-helper/v0.9.00/wamss-current.zip",
     "released_at":"2026-09-07T10:10:40.295Z"}
json.dump(d, open(p,"w",encoding="utf-8"), ensure_ascii=True, indent=2)
print(open(p, encoding='utf-8').read())
PY

echo '=== version API (browser view) ==='
curl -s https://whick.org/api/suno/version > /tmp/vapi.json
python3 - <<'PY'
import json
d = json.load(open('/tmp/vapi.json', encoding='utf-8'))["data"]
print('version:', d['version'])
print('notes   :', d['notes'])
print('notes ko ok:', d['notes'].startswith('한글'))
PY
rm -f /tmp/notes_out.txt /tmp/vapi.json
echo KO_DONE
