#!/bin/bash
echo '=== cc_software_versions schema ==='
docker exec whick-cc-db psql -U cc_app -d whick_control -c "\d cc_software_versions" 2>&1 | head -30
echo '=== current suno-helper rows ==='
docker exec whick-cc-db psql -U cc_app -d whick_control -c "SELECT v.id, v.version, v.dev_status, v.channel, v.released_at FROM cc_software_versions v JOIN cc_solutions s ON s.id=v.solution_id WHERE s.code='suno-helper' ORDER BY v.id DESC LIMIT 5;" 2>&1 | head -15
echo '=== cc_solutions row ==='
docker exec whick-cc-db psql -U cc_app -d whick_control -c "SELECT id, code, name FROM cc_solutions WHERE code='suno-helper';" 2>&1 | head -8
echo PROBE5_DONE
