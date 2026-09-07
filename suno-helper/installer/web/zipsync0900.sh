#!/bin/bash
set -e
D=/mnt/music/whick-cc/solutions/suno-helper/v0.9.00
mv /tmp/SunoHelper-Setup-v0.9.00.zip "$D/SunoHelper-Setup-v0.9.00.zip"
cp "$D/SunoHelper-Setup-v0.9.00.zip" "$D/wamss-current.zip"
chmod -R a+rX /mnt/music/whick-cc/solutions/suno-helper
echo ZIP_UPDATED
sha256sum "$D/SunoHelper-Setup-v0.9.00.zip" | cut -c1-16
ls -la "$D"
echo '--- dl check ---'
curl -s -o /dev/null -w "dl HTTP %{http_code}, %{size_download} bytes\n" "https://whick.org/dl/suno-helper/v0.9.00/wamss-current.zip" -r 0-1000
echo '--- CC file row size sync ---'
SIZE=$(stat -c%s "$D/SunoHelper-Setup-v0.9.00.zip")
docker exec whick-cc-db psql -U cc_app -d whick_control -c "UPDATE cc_core.cc_solution_files SET file_size=$SIZE WHERE file_name='SunoHelper-Setup-v0.9.00.zip';"
docker exec whick-cc-db psql -U cc_app -d whick_control -c "SELECT v.version, f.file_name, f.file_size FROM cc_core.cc_solution_files f JOIN cc_core.cc_software_versions v ON v.id=f.version_id WHERE v.solution_id=(SELECT id FROM cc_core.cc_solutions WHERE code='suno-helper') AND v.version='v0.9.00';"
echo ZIPSYNC_DONE
