#!/bin/bash
set -e
B=/mnt/music/whick-cc/solutions/suno-helper
mv /tmp/Setup.bat "$B/Setup.bat"
mv /tmp/SunoHelper-Setup-v0.9.00.zip "$B/v0.9.00/SunoHelper-Setup-v0.9.00.zip"
cp "$B/v0.9.00/SunoHelper-Setup-v0.9.00.zip" "$B/v0.9.00/wamss-current.zip"
chmod -R a+rX "$B"
echo UPDATED
echo '--- Setup.bat has flatten step? ---'
curl -s https://whick.org/dl/suno-helper/Setup.bat | grep -c 'robocopy'
echo '--- new zip has flatten inside? ---'
SIZE=$(stat -c%s "$B/v0.9.00/SunoHelper-Setup-v0.9.00.zip")
echo "zip size: $SIZE"
docker exec whick-cc-db psql -U cc_app -d whick_control -c "UPDATE cc_core.cc_solution_files SET file_size=$SIZE WHERE file_name='SunoHelper-Setup-v0.9.00.zip';" > /dev/null
echo '--- dl check ---'
curl -s -o /dev/null -w "zip %{http_code} / " "https://whick.org/dl/suno-helper/v0.9.00/wamss-current.zip" -r 0-999
curl -s -o /dev/null -w "setup %{http_code}\n" "https://whick.org/dl/suno-helper/Setup.bat"
echo SYNC_DONE
