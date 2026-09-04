#!/usr/bin/env bash
# @deprecated — use 2_control_center/scripts/solution-version.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=/dev/null
source "/data/whick-ai/2_control_center/scripts/solution-version.sh"
CODE="${WHICK_SOLUTION_CODE:-connect-wired}"
connect_version_json() { solution_version_json "$CODE" "$@"; }
connect_version_field() { solution_version_field "$CODE" "$1"; }
connect_version_bump() { solution_version_bump "$CODE" "${1:-}"; }
