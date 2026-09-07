#!/bin/bash
echo '=== tables in whick_control (all schemas) ==='
docker exec whick-cc-db psql -U cc_app -d whick_control -c "SELECT schemaname, tablename FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema') ORDER BY 1,2;" 2>&1 | head -30
echo PROBE7_DONE
