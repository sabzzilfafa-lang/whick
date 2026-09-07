#!/bin/bash
set -e
B=/mnt/music/whick-cc/solutions/suno-helper
mv /tmp/SunoHelper-Setup-v0.9.00.zip "$B/v0.9.00/SunoHelper-Setup-v0.9.00.zip"
cp "$B/v0.9.00/SunoHelper-Setup-v0.9.00.zip" "$B/v0.9.00/wamss-current.zip"
mv /tmp/launcher.pyw "$B/launcher.pyw"
chmod -R a+rX "$B"
SIZE=$(stat -c%s "$B/v0.9.00/SunoHelper-Setup-v0.9.00.zip")
docker exec whick-cc-db psql -U cc_app -d whick_control -c "UPDATE cc_core.cc_solution_files SET file_size=$SIZE WHERE file_name='SunoHelper-Setup-v0.9.00.zip';" > /dev/null
echo "zip size: $SIZE (DB synced)"
curl -s -o /dev/null -w "zip %{http_code} / " "https://whick.org/dl/suno-helper/v0.9.00/wamss-current.zip" -r 0-999
curl -s -o /dev/null -w "setup %{http_code}\n" "https://whick.org/dl/suno-helper/Setup.bat"
echo SYNC_DONE
