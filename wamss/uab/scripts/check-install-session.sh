#!/usr/bin/env bash
# 관제 설치 세션·원격 phase 상태 조회 (미니PC 재부팅 후 진단용)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=pg-install-db.sh
source "$SCRIPT_DIR/pg-install-db.sh"

CC="${WHICK_CC_API_URL:-http://127.0.0.1:8090/api/v1}"
SESSION_ID="${1:-}"

if [[ -z "$SESSION_ID" ]]; then
  SESSION_ID="$(pg_ops_row "SELECT id FROM cc_ops.cc_install_sessions ORDER BY id DESC LIMIT 1;" | tr -d '\r' || true)"
fi

if [[ -z "$SESSION_ID" ]]; then
  echo "usage: $0 [session_id]  (or set WHICK_CC_API_URL)"
  exit 1
fi

echo "== install session $SESSION_ID =="
pg_ops_query "SELECT id, phase, progress_pct, progress_msg, device_id, mb_id, hw_id_hash, created_at, updated_at, completed_at
   FROM cc_ops.cc_install_sessions WHERE id=$SESSION_ID;"

echo ""
echo "== bootstrap commands =="
pg_ops_query "SELECT id, command_type, status, last_error, sent_at, completed_at
   FROM cc_ops.cc_install_bootstrap_commands WHERE session_id=$SESSION_ID ORDER BY id;"

DEV_ID="$(pg_ops_row "SELECT device_id FROM cc_ops.cc_install_sessions WHERE id=$SESSION_ID AND device_id IS NOT NULL;" | tr -d '\r' || true)"
if [[ -n "$DEV_ID" ]]; then
  echo ""
  echo "== device $DEV_ID =="
  pg_core_query "SELECT id, hostname, serial_no, health_status, last_seen_at FROM cc_core.cc_devices WHERE id=$DEV_ID;"
fi

echo ""
echo "== hw report (latest) =="
pg_ops_query "SELECT id, session_id, hw_id_hash, left(raw_json, 200) AS raw_preview, created_at
   FROM cc_ops.cc_install_hw_reports WHERE session_id=$SESSION_ID ORDER BY created_at DESC LIMIT 1;" 2>/dev/null || echo "(no hw report row)"

echo ""
echo "CC=$CC"
