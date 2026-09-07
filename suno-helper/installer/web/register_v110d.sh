#!/bin/bash
set -e
ZIP=/mnt/music/whick-cc/solutions/suno-helper/v1.1.0/SunoHelper-Setup-v1.1.0.zip
SHA=$(sha256sum "$ZIP" | cut -d' ' -f1)
SIZE=$(stat -c%s "$ZIP")
echo "sha256: $SHA / size: $SIZE"

echo '=== register file row ==='
docker exec whick-cc-db psql -U cc_app -d whick_control -c "
INSERT INTO cc_core.cc_solution_files (version_id, file_name, storage_path, file_size, sha256)
SELECT v.id, 'SunoHelper-Setup-v1.1.0.zip', '/mnt/music/whick-cc/solutions/suno-helper/v1.1.0/SunoHelper-Setup-v1.1.0.zip', $SIZE, '$SHA'
FROM cc_core.cc_software_versions v
WHERE v.version='v1.1.0' AND v.solution_id=(SELECT id FROM cc_core.cc_solutions WHERE code='suno-helper')
AND NOT EXISTS (SELECT 1 FROM cc_core.cc_solution_files f WHERE f.version_id=v.id AND f.file_name='SunoHelper-Setup-v1.1.0.zip');
" 2>&1 | head -4

echo '=== verify ==='
docker exec whick-cc-db psql -U cc_app -d whick_control -c "SELECT v.version, f.file_name, f.file_size FROM cc_core.cc_software_versions v JOIN cc_core.cc_solution_files f ON f.version_id=v.id WHERE v.solution_id=(SELECT id FROM cc_core.cc_solutions WHERE code='suno-helper') ORDER BY v.id DESC LIMIT 3;" 2>&1 | head -10
echo REG4_DONE
