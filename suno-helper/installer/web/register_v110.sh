#!/bin/bash
set -e
VER=1.1.0
SOL=/mnt/music/whick-cc/solutions/suno-helper
ZIP=/tmp/SunoHelper-Setup-v$VER.zip

echo '=== 1. fix ownership via docker (root fs access) ==='
docker run --rm -v /mnt/music/whick-cc/solutions:/sol alpine sh -c "
  chown -R 1000:1000 /sol/suno-helper &&
  mkdir -p /sol/suno-helper/v$VER &&
  chown -R 1000:1000 /sol/suno-helper"
ls -ld "$SOL" "$SOL/v$VER"

echo '=== 2. place zips ==='
mv "$ZIP" "$SOL/v$VER/SunoHelper-Setup-v$VER.zip"
cp "$SOL/v$VER/SunoHelper-Setup-v$VER.zip" "$SOL/v$VER/wamss-current.zip"
chmod -R a+rX "$SOL"
ls -la "$SOL/v$VER/"

echo '=== 3. verify /dl/ serves it ==='
curl -s -o /dev/null -w "dl HTTP %{http_code}, %{size_download} bytes\n" "https://whick.org/dl/suno-helper/v$VER/wamss-current.zip" -r 0-1000

echo '=== 4. version API ==='
curl -s https://whick.org/api/suno/version
echo
echo '=== 5. CC DB row ==='
docker exec whick-postgres psql -U whick -d whick_cc -c "SELECT slug, name FROM solutions WHERE slug='suno-helper';" 2>&1 | head -6
echo REG1_DONE
