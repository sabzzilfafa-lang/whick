#!/usr/bin/env bash
# 설치 E2E 재시도 전 — 세션 bootstrap 명령 정리 + register_done 리셋
# Usage: ./prep-session-requeue.sh 537
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=pg-install-db.sh
source "$SCRIPT_DIR/pg-install-db.sh"

SID="${1:?session id required}"

echo "== prep install session #${SID} =="
pg_ops_query "SELECT id, device_code, phase, mb_id FROM cc_ops.cc_install_sessions WHERE id=${SID};"
pg_ops_query "SELECT id, command_type, status, attempt_count FROM cc_ops.cc_install_bootstrap_commands WHERE session_id=${SID} ORDER BY id;"

if [[ "${WHICK_PREP_YES:-0}" == "1" ]]; then
  ans=y
else
  read -r -p "Cancel commands + reset to register_done? [y/N] " ans
fi
[[ "${ans,,}" == "y" ]] || { echo "aborted"; exit 0; }

pg_ops_exec "
UPDATE cc_ops.cc_install_bootstrap_commands
  SET status='cancelled', updated_at=NOW()
  WHERE session_id=${SID} AND status != 'cancelled';
UPDATE cc_ops.cc_install_sessions
  SET phase='register_done', progress_pct=100, progress_msg='registered (requeue prep)',
      updated_at=NOW(), completed_at=NULL
  WHERE id=${SID};
"

echo "OK — 장비 keepalive 또는 orchestrator tick 후 install_linux 재큐"
pg_ops_query "SELECT id, phase FROM cc_ops.cc_install_sessions WHERE id=${SID};"
pg_ops_query "SELECT id, command_type, status FROM cc_ops.cc_install_bootstrap_commands WHERE session_id=${SID} ORDER BY id;"
