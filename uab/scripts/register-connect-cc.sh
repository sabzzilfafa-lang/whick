#!/usr/bin/env bash
# @deprecated — use register-solution-cc.sh connect-wired|connect-wireless
set -euo pipefail
CODE="${WHICK_SOLUTION_CODE:-connect-wired}"
exec /data/whick-ai/2_control_center/scripts/register-solution-cc.sh "$CODE" "${1:-}"
