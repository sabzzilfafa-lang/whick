#!/usr/bin/env bash
# Phase 7 — whick runtime (compose pull + up)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=/dev/null
. "$ROOT/bin/phase_common.sh"

phase_progress install_runtime 0 "뮤직서버 runtime 준비…"

export WHICK_RUNTIME_ROOT="${WHICK_RUNTIME_ROOT:-/opt/whick/runtime}"
export WHICK_COMPONENTS_LOCK="${WHICK_COMPONENTS_LOCK:-$ROOT/lib/components.lock.json}"
export WHICK_INSTALL_PHASE=install_runtime
# Hard stop — do not sit until CC 900s purge
export WHICK_PHASE_SCRIPT_TIMEOUT="${WHICK_PHASE_SCRIPT_TIMEOUT:-900}"
# Prefer real install-runtime messages over infinite working…
export WHICK_PHASE_TICK="${WHICK_PHASE_TICK:-0}"
RUNTIME_ROOT="$WHICK_RUNTIME_ROOT"
COMPOSE_FILE="$RUNTIME_ROOT/compose.yaml"
INSTALL_RT="$RUNTIME_ROOT/scripts/install-runtime.sh"
PHASE_INSTALL_RT="$ROOT/bin/install-runtime.sh"

# 리모컨 외부·LTE named tunnel 번들 (USB whick-boot-connect/tunnel) → install-runtime 으로 전달.
# 번들에 device-token 이 있으면 player 인증 토큰으로도 사용.
for _tdir in \
  "${WHICK_TUNNEL_BUNDLE_DIR:-}" \
  "/opt/whick-boot-connect/tunnel" \
  "${WHICK_USB_ROOT:-}/whick-boot-connect/tunnel"; do
  if [[ -n "$_tdir" && -f "$_tdir/config.yml" ]]; then
    export WHICK_TUNNEL_BUNDLE_DIR="$_tdir"
    if [[ -f "$_tdir/device-token" ]]; then
      export WHICK_REMOTE_DEVICE_TOKEN="$(tr -d '[:space:]' <"$_tdir/device-token")"
    fi
    phase_log "music tunnel 번들 발견 → $_tdir"
    break
  fi
done

if [[ "${WHICK_LINUX_INSTALL_DRY_RUN:-0}" == "1" ]]; then
  phase_log "dry-run: skip runtime deploy"
  phase_progress install_runtime 100 "runtime dry-run OK"
  touch "$PHASE_DIR/runtime_done"
  phase_progress complete 100 "설치 dry-run 완료"
  touch "$PHASE_DIR/install_complete"
  exit 0
fi

# USB Live — runtime은 SSD Ubuntu 첫 부팅에서
if [[ "${WHICK_USB_LIVE_INSTALL:-0}" == "1" ]]; then
  if [[ "${WHICK_PROD_INSTALL:-0}" == "1" ]]; then
    phase_log "prod install — runtime deferred to SSD first-boot (whick-firstboot)"
  else
    phase_log "USB live install — runtime deferred until Whick OS on disk"
  fi
  phase_progress install_runtime 100 "runtime deferred (SSD first-boot)"
  touch "$PHASE_DIR/runtime_done"
  exit 0
fi

if [[ ! -f "$COMPOSE_FILE" ]]; then
  if [[ -x "$PHASE_INSTALL_RT" ]]; then
    phase_progress install_runtime 20 "runtime 번들 배포 (phase bundle)…"
    phase_run_script install_runtime 21 89 "runtime 배포 중" "$PHASE_INSTALL_RT"
  elif [[ -x "$INSTALL_RT" ]]; then
    phase_progress install_runtime 20 "runtime 번들 배포…"
    phase_run_script install_runtime 21 89 "runtime 배포 중" "$INSTALL_RT"
  else
    phase_failed "runtime compose missing and install-runtime.sh not found"
  fi
elif [[ -x "$PHASE_INSTALL_RT" ]]; then
  phase_progress install_runtime 20 "runtime 오프라인 배포 (phase bundle)…"
  phase_run_script install_runtime 21 89 "runtime 배포 중" "$PHASE_INSTALL_RT"
elif [[ -x "$INSTALL_RT" ]]; then
  phase_progress install_runtime 20 "runtime 오프라인 배포…"
  phase_run_script install_runtime 21 89 "runtime 배포 중" "$INSTALL_RT"
else
  phase_progress install_runtime 30 "이미지 pull…"
  if command -v docker >/dev/null 2>&1; then
    COMPOSE_PROFILE=()
    if [[ "${WHICK_LOCAL_AI:-1}" != "0" ]]; then
      COMPOSE_PROFILE=(--profile local-ai)
    fi
    set +e
    docker compose -f "$COMPOSE_FILE" "${COMPOSE_PROFILE[@]}" pull
    pull_rc=$?
    set -e
    if [[ "$pull_rc" -ne 0 ]]; then
      phase_failed "docker compose pull 실패 (exit $pull_rc)"
    fi
    phase_progress install_runtime 60 "서비스 기동…"
    set +e
    docker compose -f "$COMPOSE_FILE" "${COMPOSE_PROFILE[@]}" up -d
    up_rc=$?
    set -e
    if [[ "$up_rc" -ne 0 ]]; then
      phase_failed "docker compose up 실패 (exit $up_rc)"
    fi
  else
    phase_failed "docker not available"
  fi
fi

phase_progress install_runtime 100 "runtime 기동 완료"
touch "$PHASE_DIR/runtime_done"
phase_progress complete 100 "설치 완료"
touch "$PHASE_DIR/install_complete"
