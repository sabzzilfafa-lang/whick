#!/bin/bash
set -e
D=/mnt/music/whick-cc/solutions/suno-helper/v0.9.00
ls /tmp/SunoHelper-Setup-v0.9.00.zip
mv /tmp/SunoHelper-Setup-v0.9.00.zip "$D/SunoHelper-Setup-v0.9.00.zip"
cp "$D/SunoHelper-Setup-v0.9.00.zip" "$D/wamss-current.zip"
chmod -R a+rX /mnt/music/whick-cc/solutions/suno-helper
SIZE=$(stat -c%s "$D/SunoHelper-Setup-v0.9.00.zip")
echo "zip size: $SIZE"
docker exec whick-cc-db psql -U cc_app -d whick_control -c "UPDATE cc_core.cc_solution_files SET file_size=$SIZE WHERE file_name='SunoHelper-Setup-v0.9.00.zip';"
curl -s -o /dev/null -w "zip %{http_code}\n" "https://whick.org/dl/suno-helper/v0.9.00/wamss-current.zip" -r 0-999
echo SWAP_DONE
