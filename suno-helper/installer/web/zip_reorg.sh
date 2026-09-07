#!/bin/bash
# zip SSOT 재구성: v1.1.0 -> v0.9.00 디렉터리, 이전 zip 정리
set -e
B=/mnt/music/whick-cc/solutions/suno-helper
mv "$B/v1.1.0/SunoHelper-Setup-v1.1.0.zip" "$B/v1.1.0/SunoHelper-Setup-v0.9.00.zip" 2>/dev/null || true
mkdir -p "$B/v0.9.00"
mv "$B/v1.1.0/SunoHelper-Setup-v0.9.00.zip" "$B/v0.9.00/SunoHelper-Setup-v0.9.00.zip"
cp "$B/v0.9.00/SunoHelper-Setup-v0.9.00.zip" "$B/v0.9.00/wamss-current.zip"
chmod -R a+rX "$B"
rmdir "$B/v1.1.0" 2>/dev/null || ls -la "$B/v1.1.0"
ls -la "$B" "$B/v0.9.00"
echo '--- dl checks ---'
curl -s -o /dev/null -w "v0.9.00 zip HTTP %{http_code}, %{size_download}B\n" "https://whick.org/dl/suno-helper/v0.9.00/wamss-current.zip" -r 0-1000
curl -s -o /dev/null -w "Setup.bat HTTP %{http_code}\n" "https://whick.org/dl/suno-helper/Setup.bat"
echo '--- version API ---'
curl -s https://whick.org/api/suno/version | head -c 200
echo
echo ZIP_REORG_DONE
