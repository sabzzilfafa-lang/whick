#!/bin/bash
echo '=== tables ==='
docker exec whick-cc-db psql -U cc_app -d whick_control -c "\dt" 2>&1 | head -25
echo '=== the SQL in sunoLicense.js ==='
docker exec whick-cc-site-api sed -n '255,295p' /app/src/packages/site/routes/sunoLicense.js
echo PROBE4_DONE
