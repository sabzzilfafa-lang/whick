#!/bin/bash
echo '=== databases in whick-cc-db ==='
docker exec whick-cc-db psql -U cc_app -d whick_control -c "\l" 2>&1 | head -15
echo '=== try whick_cc db ==='
docker exec whick-cc-db psql -U cc_app -d whick_cc -c "\dt" 2>&1 | grep -iE 'cc_solutions|cc_software|solutions|software_ver' | head -8
docker exec whick-cc-db psql -U cc_app -d whick_cc -c "\dt" 2>&1 | head -20
echo PROBE6_DONE
