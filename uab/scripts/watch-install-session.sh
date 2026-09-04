#!/usr/bin/env bash
# 미니PC 온라인(keepalive) 감지 → Phase 5~7 완료까지 감시 (재큐 없음 — CC orchestrator가 담당)
#
# Usage:
#   WHICK_WATCH_SESSION=651 ./watch-install-session.sh
#   WHICK_WATCH_CUSTOMER=28 ./watch-install-session.sh   # 최신 미완료 세션 자동 선택
#   nohup env WHICK_WATCH_SESSION=651 ./watch-install-session.sh &
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=pg-install-db.sh
source "$SCRIPT_DIR/pg-install-db.sh"

SID="${WHICK_WATCH_SESSION:-}"
CUST="${WHICK_WATCH_CUSTOMER:-}"
POLL="${WHICK_WATCH_POLL_SEC:-30}"
ONLINE_SEC="${WHICK_ONLINE_THRESHOLD_SEC:-180}"
SCRATCH="${WHICK_SANDBOX_SCRATCH:-/data/whick-ai/sandbox-scratch}"
STAMP="$(TZ=Asia/Seoul date +%Y%m%d-%H%M%S)"
RUN_DIR="$SCRATCH/runs/install-watch-${STAMP}"
LOG="$RUN_DIR/watch.log"

mkdir -p "$RUN_DIR"
exec > >(tee -a "$LOG") 2>&1

resolve_session_id() {
  if [[ -n "$SID" ]]; then
    return 0
  fi
  if [[ -z "$CUST" ]]; then
    echo "WHICK_WATCH_SESSION or WHICK_WATCH_CUSTOMER required" >&2
    exit 2
  fi
  SID="$(pg_ops_row "
    SELECT id FROM cc_ops.cc_install_sessions
    WHERE customer_id=${CUST}
      AND phase NOT IN ('complete','preinstalled')
    ORDER BY updated_at DESC, id DESC
    LIMIT 1;
  " | tr -d '\r' || true)"
  if [[ -z "$SID" ]]; then
    SID="$(pg_ops_row "
      SELECT id FROM cc_ops.cc_install_sessions
      WHERE customer_id=${CUST}
      ORDER BY id DESC LIMIT 1;
    " | tr -d '\r' || true)"
  fi
  if [[ -z "$SID" ]]; then
    echo "no install session for customer ${CUST}" >&2
    exit 2
  fi
  echo "[watch] resolved customer=${CUST} -> session #${SID}"
}

session_row() {
  pg_ops_row "
    SELECT s.id, s.device_code, s.phase, s.progress_pct, COALESCE(s.progress_msg,''),
           COALESCE(s.mb_id,''), COALESCE(s.device_id::text,''), COALESCE(s.customer_id::text,''),
           s.updated_at,
           CASE WHEN s.updated_at >= NOW() - INTERVAL '${ONLINE_SEC} seconds' THEN 1 ELSE 0 END
    FROM cc_ops.cc_install_sessions s WHERE s.id=${SID};
  "
}

device_online() {
  local did="$1"
  [[ -z "$did" || "$did" == "NULL" ]] && return 1
  local row
  row="$(pg_core_row "
    SELECT CASE WHEN last_seen_at >= NOW() - INTERVAL '${ONLINE_SEC} seconds' THEN 1 ELSE 0 END
    FROM cc_core.cc_devices WHERE id=${did};" | tr -d '\r' || true)"
  [[ "$row" == "1" ]]
}

format_line() {
  local row="$1"
  echo "[$(TZ=Asia/Seoul date +%H:%M:%S)] $row"
}

resolve_session_id

echo "== install watch $STAMP =="
echo "session=#${SID} poll=${POLL}s online_threshold=${ONLINE_SEC}s"
echo "log=$LOG"
echo "모니터 전용 — 재큐는 CC orchestrator / USB 재부팅으로 새 세션"

LAST_PHASE=""
SEEN_ONLINE=0

while true; do
  row="$(session_row || true)"
  if [[ -z "$row" ]]; then
    format_line "session #${SID} deleted (purge 또는 새 USB 부팅) — watch 종료"
    exit 3
  fi

  IFS=$'\t' read -r _ code phase pct msg mb_id did cust_id updated sess_online <<< "$row"
  online=0
  if [[ "$sess_online" == "1" ]] || device_online "$did"; then
    online=1
    SEEN_ONLINE=1
  fi

  if [[ "$phase" != "$LAST_PHASE" ]]; then
    format_line "${SID}|${code}|${phase}|${pct}|${msg} · online=${online} · ${mb_id}|${updated}"
    LAST_PHASE="$phase"
  fi

  case "$phase" in
    complete)
      format_line "COMPLETE session #${SID} — 설치 완료"
      if [[ -n "$cust_id" && "$cust_id" != "NULL" ]]; then
        pg_core_exec "UPDATE cc_core.cc_customer_install_portals SET active_install_session_id=${SID}, updated_at=NOW() WHERE customer_id=${cust_id};" || true
      fi
      exit 0
      ;;
    failed)
      format_line "FAILED/purged session #${SID} — CC가 미완료 세션 삭제 정책 적용 (USB 재부팅)"
      exit 1
      ;;
  esac

  sleep "$POLL"
done
