#!/usr/bin/env bash
# UAB Phase 0~8 오케스트레이터 — USB Live RAM 에서 실행
# SSOT: install/UAB-INSTALL-PROCESS.md
set -euo pipefail

UAB_ROOT="$(cd "$(dirname "$0")" && pwd)"
BIN="$UAB_ROOT/bin"
PHASE_DIR="${WHICK_PHASE_DIR:-/tmp/whick-phases}"
STATE="${WHICK_UAB_STATE:-/tmp/whick-uab-state.json}"
INSTALL_PATH="${WHICK_INSTALL_PATH:-diy}"
CC_URL="${WHICK_CC_API_URL:-https://admin.whick.org/api/v1}"

mkdir -p "$PHASE_DIR"
export WHICK_CC_API_URL="$CC_URL"
export PYTHONUNBUFFERED=1

log() { echo "[boot.sh] $*"; }

wait_file() {
  local f="$1" timeout="${2:-3600}" elapsed=0
  log "wait: $f"
  while [[ ! -f "$f" ]]; do
    sleep 2
    elapsed=$((elapsed + 2))
    if (( elapsed >= timeout )); then
      log "TIMEOUT waiting for $f"
      touch "$PHASE_DIR/install_failed"
      exit 1
    fi
  done
}

run_phase() {
  local name="$1" script="$UAB_ROOT/phases/${name}.sh"
  if [[ -x "$script" ]]; then
    log "phase: $name"
    bash "$script"
  else
    log "phase stub (skip): $name"
  fi
}

log "Whick UAB boot — $INSTALL_PATH"

# 0.1 네트워크
if [[ -x "$BIN/network-setup.sh" ]]; then
  bash "$BIN/network-setup.sh" || log "WARN: network-setup partial failure"
fi

# 0.2 HW 수집
bash "$BIN/hw_collect.sh"

# 0.3 CC 세션 + bootstrap agent 백그라운드
python3 "$BIN/bootstrap-agent.py" --state "$STATE" --phase-dir "$PHASE_DIR" &
AGENT_PID=$!
trap 'kill $AGENT_PID 2>/dev/null || true' EXIT

# 0.4 스마트폰 UI
python3 "$BIN/local_web.py" --state "$STATE" --phase-dir "$PHASE_DIR" &
WEB_PID=$!

log "스마트폰: http://$(hostname -I 2>/dev/null | awk '{print $1}'):8765"
log "장비코드: $(python3 -c "import json;print(json.load(open('$STATE')).get('device_code','…'))" 2>/dev/null || echo '…')"

# Phase 2 동의
wait_file "$PHASE_DIR/consent_done" 7200

# Phase 3~6 HW · proceed
wait_file "$PHASE_DIR/proceed_confirmed" 7200

# Phase 4 고객등록 (diy)
if [[ "$INSTALL_PATH" = "diy" ]]; then
  wait_file "$PHASE_DIR/register_done" 7200
else
  log "factory path — register SKIP"
  touch "$PHASE_DIR/register_done"
fi

# Phase 5~7 SSD 설치 (고객 UI: 진행률만)
run_phase "02_linux_install"
run_phase "03_docker"
run_phase "04_runtime"

if [[ -f "$PHASE_DIR/install_failed" ]]; then
  log "install failed — see phase logs"
  exit 1
fi

if [[ "${WHICK_LINUX_INSTALL_DRY_RUN:-0}" == "1" ]]; then
  log "dry-run — phases finished (no install_complete marker for CC)"
else
  touch "$PHASE_DIR/install_complete"
  log "UAB complete — USB 제거 후 SSD 부팅"
fi

kill $WEB_PID $AGENT_PID 2>/dev/null || true
wait $WEB_PID $AGENT_PID 2>/dev/null || true
