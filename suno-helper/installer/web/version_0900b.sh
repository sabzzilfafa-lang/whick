#!/bin/bash
# psql 개별 -c 실행 (heredoc 문제 우회)
set -e
PG="docker exec whick-cc-db psql -U cc_app -d whick_control -v ON_ERROR_STOP=1 -c"
SID="(SELECT id FROM cc_core.cc_solutions WHERE code='suno-helper')"

echo '=== A. archive old deploy rows ==='
$PG "UPDATE cc_core.cc_software_versions SET dev_status='archived' WHERE solution_id=$SID AND version IN ('v1.0.0','v1.1.0') AND dev_status='deploy';"

echo '=== B. insert v0.9.00 ==='
$PG "INSERT INTO cc_core.cc_software_versions (solution_id, version, dev_status, channel, release_notes, released_at) VALUES ($SID, 'v0.9.00', 'deploy', 'stable', '한글 가사 의역(EN→KO) 지원, 브라우저 닫힘 자동 종료, Intel QSV 인코더 지원, 웹 대시보드 설치·실행(suno-helper://) 흐름', now());"

echo '=== C. refile solution_files ==='
$PG "UPDATE cc_core.cc_solution_files f SET version_id=(SELECT id FROM cc_core.cc_software_versions WHERE version='v0.9.00' AND solution_id=$SID), file_name='SunoHelper-Setup-v0.9.00.zip' WHERE file_name='SunoHelper-Setup-v1.1.0.zip';"

echo '=== D. verify ==='
docker exec whick-cc-db psql -U cc_app -d whick_control -c "SELECT version, dev_status FROM cc_core.cc_software_versions WHERE solution_id=$SID ORDER BY id DESC LIMIT 4;"
docker exec whick-cc-db psql -U cc_app -d whick_control -c "SELECT v.version, f.file_name FROM cc_core.cc_solution_files f JOIN cc_core.cc_software_versions v ON v.id=f.version_id WHERE v.solution_id=$SID;"
docker exec whick-cc-db psql -U cc_app -d whick_control -c "SELECT release_notes FROM cc_core.cc_software_versions WHERE version='v0.9.00';"

echo '=== E. version API ==='
curl -s https://whick.org/api/suno/version
echo
echo SQL2_DONE
