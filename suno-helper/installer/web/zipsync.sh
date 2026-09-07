#!/bin/bash
set -e
D=/mnt/music/whick-cc/solutions/suno-helper/v1.1.0
mv /tmp/SunoHelper-Setup-v1.1.0.zip "$D/SunoHelper-Setup-v1.1.0.zip"
cp "$D/SunoHelper-Setup-v1.1.0.zip" "$D/wamss-current.zip"
chmod -R a+rX /mnt/music/whick-cc/solutions/suno-helper
echo ZIP_UPDATED
sha256sum "$D/SunoHelper-Setup-v1.1.0.zip" | cut -c1-16
ls -la "$D"
echo '--- dl check ---'
curl -s -o /dev/null -w "dl HTTP %{http_code}, %{size_download} bytes\n" "https://whick.org/dl/suno-helper/v1.1.0/wamss-current.zip" -r 0-1000
echo ZIPSYNC_DONE
