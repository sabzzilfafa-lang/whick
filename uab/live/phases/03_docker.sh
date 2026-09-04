#!/usr/bin/env bash
# Phase 6 — Docker on SSD (chroot or target OS)
# Prefer phase-bundle install-docker.sh (CC-fresh). Runtime copy may be stale from a prior fail.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=/dev/null
. "$ROOT/bin/phase_common.sh"

phase_progress install_docker 0 "Docker 준비…"

export WHICK_RUNTIME_ROOT="${WHICK_RUNTIME_ROOT:-/opt/whick/runtime}"
export WHICK_COMPONENTS_LOCK="${WHICK_COMPONENTS_LOCK:-$ROOT/lib/components.lock.json}"
export WHICK_INSTALL_PHASE=install_docker
# Hang root cause: docker.com apt path. Default = CC/offline debs only (online opt-in).
export WHICK_SKIP_ONLINE_INSTALL="${WHICK_SKIP_ONLINE_INSTALL:-1}"
export WHICK_DPKG_TIMEOUT="${WHICK_DPKG_TIMEOUT:-180}"
export WHICK_DOCKER_FETCH_TIMEOUT="${WHICK_DOCKER_FETCH_TIMEOUT:-180}"
# Whole phase hard stop — never sit in fake working… until CC 900s purge
export WHICK_PHASE_SCRIPT_TIMEOUT="${WHICK_PHASE_SCRIPT_TIMEOUT:-420}"
# Real install-docker messages (CC deb / dpkg) must show — disable masking tick
export WHICK_PHASE_TICK="${WHICK_PHASE_TICK:-0}"

RUNTIME_ROOT="$WHICK_RUNTIME_ROOT"
INSTALL_DOCKER="$RUNTIME_ROOT/scripts/install-docker.sh"
PHASE_INSTALL_DOCKER="$ROOT/bin/install-docker.sh"

if [[ "${WHICK_LINUX_INSTALL_DRY_RUN:-0}" == "1" ]]; then
  phase_log "dry-run: skip docker install"
  phase_progress install_docker 100 "docker dry-run OK"
  touch "$PHASE_DIR/docker_done"
  exit 0
fi

# USB Live — Docker는 SSD Ubuntu 첫 부팅에서 (whick-firstboot)
if [[ "${WHICK_USB_LIVE_INSTALL:-0}" == "1" ]]; then
  if [[ "${WHICK_PROD_INSTALL:-0}" == "1" ]]; then
    phase_log "prod install — docker deferred to SSD first-boot (whick-firstboot)"
  else
    phase_log "USB live install — docker deferred until Whick OS on disk"
  fi
  phase_progress install_docker 100 "docker deferred (SSD first-boot)"
  touch "$PHASE_DIR/docker_done"
  exit 0
fi

# Phase-bundle FIRST (always refreshed from CC). Runtime script only if bundle missing.
if [[ -x "$PHASE_INSTALL_DOCKER" ]]; then
  phase_progress install_docker 20 "Docker 설치 중 (phase bundle)…"
  phase_log "using phase-bundle install-docker (skip_online=$WHICK_SKIP_ONLINE_INSTALL timeout=${WHICK_PHASE_SCRIPT_TIMEOUT}s)"
  phase_run_script install_docker 21 89 "Docker 설치 중" "$PHASE_INSTALL_DOCKER"
elif [[ -x "$INSTALL_DOCKER" ]]; then
  phase_progress install_docker 20 "Docker 설치 중…"
  phase_log "WARN phase-bundle install-docker missing — fallback runtime copy"
  phase_run_script install_docker 21 89 "Docker 설치 중" "$INSTALL_DOCKER"
else
  ALT="${WHICK_INSTALL_RUNTIME:-/opt/whick/runtime}/scripts/install-docker.sh"
  if [[ -x "$ALT" ]]; then
    phase_run_script install_docker 21 89 "Docker 설치 중" "$ALT"
  else
    phase_failed "install-docker.sh missing (build music-01 runtime bundle on lab server)"
  fi
fi

phase_progress install_docker 100 "Docker 설치 완료"
touch "$PHASE_DIR/docker_done"
