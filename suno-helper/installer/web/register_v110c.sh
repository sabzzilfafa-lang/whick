#!/bin/bash
set -e
echo '=== 1. insert v1.1.0 deploy row ==='
docker exec whick-cc-db psql -U cc_app -d whick_control -c "
UPDATE cc_core.cc_software_versions SET dev_status='archived' WHERE solution_id=(SELECT id FROM cc_core.cc_solutions WHERE code='suno-helper') AND version='v1.0.0' AND dev_status='deploy';
INSERT INTO cc_core.cc_software_versions (solution_id, version, dev_status, channel, release_notes, released_at)
VALUES ((SELECT id FROM cc_core.cc_solutions WHERE code='suno-helper'), 'v1.1.0', 'deploy', 'stable',
        'Web-driven install: Setup.bat one-click downloader, suno-helper:// protocol launch from whick.org, local direct-run guard',
        now());
" 2>&1 | head -6

echo '=== 2. verify version API ==='
curl -s https://whick.org/api/suno/version
echo

echo '=== 3. solution_files register (like v1.0.0) ==='
docker exec whick-cc-db psql -U cc_app -d whick_control -c "\d cc_core.cc_solution_files" 2>&1 | head -20
docker exec whick-cc-db psql -U cc_app -d whick_control -c "SELECT * FROM cc_core.cc_solution_files WHERE solution_id=(SELECT id FROM cc_core.cc_solutions WHERE code='suno-helper') LIMIT 5;" 2>&1 | head -12
echo REG3_DONE
