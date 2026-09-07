#!/bin/bash
set -e
echo '=== schema of solution_versions ==='
docker exec whick-cc-db psql -U cc_app -d whick_control -c "\d solution_versions" 2>&1 | head -25
echo '=== current suno rows ==='
docker exec whick-cc-db psql -U cc_app -d whick_control -c "SELECT id, solution_id, version, dev_status, channel, created_at FROM solution_versions v JOIN solutions s ON s.id=v.solution_id WHERE s.code='suno-helper' ORDER BY v.id DESC LIMIT 5;" 2>&1 | head -15
echo DBPROBE_DONE
