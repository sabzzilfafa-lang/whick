#!/bin/bash
# CC 버전관리: 한글 복구 + v0.9.00 deploy 행 교체 + 카탈로그 0.9.x
set -e

echo '=== 1. 현재 상태 ==='
docker exec whick-cc-db psql -U cc_app -d whick_control -c "SELECT version, dev_status, release_notes FROM cc_core.cc_software_versions WHERE solution_id=(SELECT id FROM cc_core.cc_solutions WHERE code='suno-helper') ORDER BY id DESC LIMIT 4;" 2>&1 | head -12

echo '=== 2. v1.1.0 deploy -> archived, v0.9.00 deploy insert (정상 UTF-8 노트) ==='
docker exec whick-cc-db psql -U cc_app -d whick_control <<'SQL'
UPDATE cc_core.cc_software_versions
SET dev_status='archived'
WHERE solution_id=(SELECT id FROM cc_core.cc_solutions WHERE code='suno-helper')
  AND version IN ('v1.0.0','v1.1.0') AND dev_status='deploy';

INSERT INTO cc_core.cc_software_versions (solution_id, version, dev_status, channel, release_notes, released_at)
VALUES ((SELECT id FROM cc_core.cc_solutions WHERE code='suno-helper'), 'v0.9.00', 'deploy', 'stable',
        '한글 가사 의역(EN→KO) 지원, 브라우저 닫힘 자동 종료, Intel QSV 인코더 지원, 웹 대시보드 설치·실행(suno-helper://) 흐름',
        now());
SQL

echo '=== 3. solution_files: v0.9.00용 등록 (v1.1.0 행 재사용 - 파일 동일) ==='
docker exec whick-cc-db psql -U cc_app -d whick_control <<'SQL'
UPDATE cc_core.cc_solution_files f
SET version_id = (SELECT id FROM cc_core.cc_software_versions WHERE version='v0.9.00'
                  AND solution_id=(SELECT id FROM cc_core.cc_solutions WHERE code='suno-helper')),
    file_name = 'SunoHelper-Setup-v0.9.00.zip'
WHERE file_name='SunoHelper-Setup-v1.1.0.zip';
SQL

echo '=== 4. catalog: version_semver 0.9.x + zip_name ==='
python3 - <<'PY'
import json
p = "/data/whick-ai/2_control_center/config/solutions-catalog.json"
c = json.load(open(p, encoding="utf-8"))
e = c["solutions"]["suno-helper"]
e["version_semver"] = "0.9.x"
e["package"]["zip_name"] = "SunoHelper-Setup-v0.9.00.zip"
json.dump(c, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("catalog:", e["version_semver"], e["package"]["zip_name"])
PY

echo '=== 5. version file SSOT ==='
cat > /data/whick-ai/2_control_center/config/solutions/suno-helper.json <<EOF
{
  "product": "suno-helper",
  "version": "0.9.00",
  "notes": "한글 가사 의역(EN→KO) 지원, 브라우저 닫힘 자동 종료, Intel QSV 인코더 지원, 웹 대시보드 설치·실행(suno-helper://) 흐름",
  "url": "https://whick.org/dl/suno-helper/v0.9.00/wamss-current.zip",
  "released_at": "$(date -u +%Y-%m-%dT%H:%M:%S.000Z)"
}
EOF
cat /data/whick-ai/2_control_center/config/solutions/suno-helper.json

echo '=== 6. DB 최종 확인 ==='
docker exec whick-cc-db psql -U cc_app -d whick_control -c "SELECT version, dev_status, release_notes FROM cc_core.cc_software_versions WHERE solution_id=(SELECT id FROM cc_core.cc_solutions WHERE code='suno-helper') ORDER BY id DESC LIMIT 4;" 2>&1 | head -12
docker exec whick-cc-db psql -U cc_app -d whick_control -c "SELECT v.version, f.file_name FROM cc_core.cc_solution_files f JOIN cc_core.cc_software_versions v ON v.id=f.version_id JOIN cc_core.cc_solutions s ON s.id=v.solution_id WHERE s.code='suno-helper';" 2>&1 | head -8

echo '=== 7. version API ==='
curl -s https://whick.org/api/suno/version
echo
echo DB_DONE
