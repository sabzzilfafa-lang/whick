#!/bin/bash
# v1.1.0 빈 디렉터리 정리 + v1.0.0 이전 패키지 처리
set -e
B=/mnt/music/whick-cc/solutions/suno-helper
rmdir "$B/v1.1.0" 2>/dev/null && echo "v1.1.0 dir removed" || { ls -la "$B/v1.1.0"; }
echo '--- final layout ---'
ls -la "$B"
echo '--- CC dashboard (version list) sanity: API + dl all green ---'
curl -s -o /dev/null -w "suno.html %{http_code} / " https://whick.org/suno.html
curl -s -o /dev/null -w "suno-app %{http_code} / " https://whick.org/suno-app.html
curl -s -o /dev/null -w "setup.bat %{http_code} / " https://whick.org/dl/suno-helper/Setup.bat
curl -s -o /dev/null -w "zip %{http_code}\n" https://whick.org/dl/suno-helper/v0.9.00/wamss-current.zip -r 0-999
echo CLEAN_DONE
