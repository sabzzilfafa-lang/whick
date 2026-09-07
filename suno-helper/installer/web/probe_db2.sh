#!/bin/bash
set -e
echo '=== catalog entry for suno-helper ==='
grep -A 20 '"suno-helper"' /data/whick-ai/2_control_center/config/solutions-catalog.json | head -30
echo '=== version file ==='
cat /data/whick-ai/2_control_center/config/solutions/suno-helper/version.json 2>/dev/null || find /data/whick-ai/2_control_center/config -name '*.json' -path '*suno*' | head -5
echo '=== db creds used by CC ==='
grep -rn 'whick_cc\|POSTGRES' /data/whick-ai/2_control_center/docker-compose.yml 2>/dev/null | head -8
docker exec whick-cc-db env 2>/dev/null | grep -i postgres | head -5
echo PROBE2_DONE
