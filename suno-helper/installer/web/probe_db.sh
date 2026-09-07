#!/bin/bash
set -e
VER=1.1.0
NOTES="Web-driven install: Setup.bat one-click downloader, suno-helper:// protocol launch from whick.org, local direct-run guard"

echo '=== 1. CC DB register via whick-cc-db ==='
docker exec whick-cc-db psql -U whick -d whick_cc -c "SELECT slug FROM solutions WHERE slug='suno-helper';" 2>&1 | head -5
docker exec whick-cc-db psql -U whick -d whick_cc -c "\dt" 2>&1 | grep -iE 'solutions|version' | head -6 || true

echo '=== 2. register-solution-cc.sh usage ==='
head -40 /data/whick-ai/2_control_center/scripts/register-solution-cc.sh
echo PROBE_DONE
