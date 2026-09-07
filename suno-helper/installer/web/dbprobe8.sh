#!/bin/bash
echo '=== software/solution version tables ==='
docker exec whick-cc-db psql -U cc_app -d whick_control -c "SELECT schemaname, tablename FROM pg_tables WHERE tablename LIKE '%software%' OR tablename LIKE '%solution%' ORDER BY 2;" 2>&1 | head -15
echo '=== cc_software_versions rows for suno-helper ==='
docker exec whick-cc-db psql -U cc_app -d whick_control -c "SELECT v.id, v.version, v.dev_status, v.channel, v.released_at FROM cc_core.cc_software_versions v JOIN cc_core.cc_solutions s ON s.id=v.solution_id WHERE s.code='suno-helper' ORDER BY v.id DESC LIMIT 5;" 2>&1 | head -15
echo PROBE8_DONE
