#!/usr/bin/env bash
# Phase 6 — Docker CE · CC 우선(디폴트) · 인터넷은 동일 핀 버전 비상 폴백만
# 정책: cc_first_internet_emergency · latest 금지
set -euo pipefail

CACHE="${WHICK_INSTALL_CACHE:-/var/lib/whick/install-cache}"
DEB_DIR="$CACHE/docker-debs"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

_resolve_lock() {
  for candidate in \
    "${WHICK_COMPONENTS_LOCK:-}" \
    "${WHICK_REMOTE_PHASE_ROOT:-}/lib/components.lock.json" \
    "/var/lib/whick/remote-phases/lib/components.lock.json" \
    "$SCRIPT_DIR/../lib/components.lock.json" \
    "/opt/whick/runtime/components.lock.json"; do
    [[ -n "$candidate" && -f "$candidate" ]] && { echo "$candidate"; return 0; }
  done
  return 1
}
LOCK="$(_resolve_lock || echo '')"
# shellcheck source=/dev/null
. "$SCRIPT_DIR/whick-dual-install-common.sh"

log() { dual_log "docker: $*"; }

docker_progress() {
  local pct="$1" msg="$2"
  for candidate in \
    "${WHICK_REMOTE_PHASE_ROOT:-}/bin/cc_progress.py" \
    "$SCRIPT_DIR/cc_progress.py"; do
    if [[ -f "$candidate" ]]; then
      python3 "$candidate" --phase install_docker --pct "$pct" --msg "$msg" 2>/dev/null || true
      break
    fi
  done
  log "$msg"
}

finish_ok() {
  local source="$1"
  log "OK source=${source} $(docker --version) · $(docker compose version)"
  docker_progress 30 "Docker 서비스 등록 중…"
  systemctl enable --now docker 2>/dev/null || true
  sleep 1
  docker_progress 40 "Docker 데몬 확인 중…"
  for i in $(seq 1 5); do
    if docker_ready; then break; fi
    docker_progress $((40 + i * 3)) "Docker 대기 중… (${i}/5)"
    sleep 2
  done
  docker_progress 100 "Docker 설치 완료 (${source})"
  exit 0
}

if docker_ready; then
  log "already installed: $(docker --version)"
  docker_progress 100 "Docker 이미 설치됨"
  exit 0
fi

docker_progress 5 "Docker 확인 중…"

install_from_debs() {
  local dir="$1"
  [[ -d "$dir" ]] || return 1
  local deb_count
  deb_count="$(find "$dir" -maxdepth 1 -name '*.deb' 2>/dev/null | wc -l | tr -d ' ')"
  [[ "${deb_count:-0}" -gt 0 ]] || return 1
  log "offline debs (${deb_count}) from $dir"
  export DEBIAN_FRONTEND=noninteractive
  (
    pct=12
    while [[ $pct -le 28 ]]; do
      sleep 2
      pct=$((pct + 1))
      docker_progress "$pct" "Docker 패키지 설치 중… (${pct}%)" 2>/dev/null || true
    done
  ) &
  DPKG_TICK_PID=$!
  (
    cd "$dir"
    dpkg -i ./*.deb
  ) || log "offline dpkg -i had errors — continuing"
  kill "$DPKG_TICK_PID" 2>/dev/null || true
  wait "$DPKG_TICK_PID" 2>/dev/null || true
  if ! docker_ready; then
    log "offline apt local debs retry"
    docker_progress 29 "Docker 패키지 복구 중…"
    (
      cd "$dir"
      apt-get install -y --no-install-recommends ./*.deb
    ) || true
  fi
  docker_ready
}

fetch_cc_deb_bundle() {
  local BUNDLE_NAME="" DEB_SHA="" DEB_SIZE="" TAR
  [[ -f "$LOCK" ]] && command -v python3 >/dev/null 2>&1 || {
    log "SKIP CC: lock not found or python3 missing (LOCK=$LOCK)"
    return 1
  }
  log "lock found at $LOCK"
  BUNDLE_NAME="$(python3 - <<'PY' "$LOCK"
import json, sys
lock = json.load(open(sys.argv[1]))
print(lock.get("components", {}).get("docker_ce", {}).get("deb_bundle", ""))
PY
)"
  DEB_SHA="$(python3 - <<'PY' "$LOCK"
import json, sys
lock = json.load(open(sys.argv[1]))
print(lock.get("components", {}).get("docker_ce", {}).get("deb_sha256", ""))
PY
)"
  DEB_SIZE="$(python3 - <<'PY' "$LOCK"
import json, sys
lock = json.load(open(sys.argv[1]))
print(lock.get("components", {}).get("docker_ce", {}).get("deb_size_bytes", ""))
PY
)"
  [[ -n "$BUNDLE_NAME" ]] || {
    log "SKIP CC: BUNDLE_NAME empty"
    return 1
  }
  log "CC bundle name=$BUNDLE_NAME"
  TAR="$CACHE/$BUNDLE_NAME"
  if [[ -f "$TAR" ]]; then
    if [[ -n "$DEB_SHA" ]] && ! verify_file_sha256 "$TAR" "$DEB_SHA"; then
      log "stale deb bundle removed (sha mismatch)"
      rm -f "$TAR"
    elif [[ -n "$DEB_SIZE" ]] && [[ "$(stat -c%s "$TAR")" != "$DEB_SIZE" ]]; then
      log "stale deb bundle removed (size mismatch)"
      rm -f "$TAR"
    fi
  fi
  if [[ ! -f "$TAR" ]]; then
    log "CC fetch $BUNDLE_NAME (source=cc)"
    (
      pct=50
      while [[ $pct -le 70 ]]; do
        docker_progress "$pct" "Docker deb(CC) 다운로드… (${pct}%)"
        sleep 2
        pct=$((pct + 1))
      done
    ) &
    CC_TICK_PID=$!
    set +e
    "$SCRIPT_DIR/whick-fetch-artifact.sh" \
      --name "$BUNDLE_NAME" \
      --dest "$TAR" \
      ${DEB_SHA:+--sha256 "$DEB_SHA"} \
      --prefer-cc \
      --url "$(cc_artifact_url "$BUNDLE_NAME")" \
      --url "https://whick.org/downloads/$BUNDLE_NAME"
    _cc_fetch_rc=$?
    set -e
    log "CC fetch exit=$_cc_fetch_rc"
    kill "$CC_TICK_PID" 2>/dev/null || true
    wait "$CC_TICK_PID" 2>/dev/null || true
    [[ "$_cc_fetch_rc" -eq 0 && -f "$TAR" ]] || return 1
  fi
  rm -rf "${DEB_DIR:?}"/*
  mkdir -p "$DEB_DIR"
  case "$TAR" in
    *.tar.zst)
      command -v zstd >/dev/null 2>&1 || { log "ERROR: zstd missing for $TAR"; return 1; }
      tar -I zstd -xf "$TAR" -C "$DEB_DIR"
      ;;
    *.tar.gz|*.tgz) tar -xzf "$TAR" -C "$DEB_DIR" ;;
    *) cp -f "$TAR" "$DEB_DIR/" ;;
  esac
  install_from_debs "$DEB_DIR"
}

mkdir -p "$DEB_DIR"

# 1) SSD/USB staged offline debs
docker_progress 10 "Docker 로컬/오프라인 deb 확인…"
if install_from_debs "$DEB_DIR" \
  || install_from_debs "${WHICK_RUNTIME_ROOT:-/opt/whick/runtime}/offline/docker-debs"; then
  finish_ok "offline-local"
fi

# 2) CC 디폴트 — 검증된 핀 deb 번들
docker_progress 45 "Docker CC 아티팩트…"
if fetch_cc_deb_bundle; then
  finish_ok "cc"
fi

# 3) 비상 — 인터넷 apt (lock 핀 버전만 · latest 금지)
if [[ "${WHICK_SKIP_ONLINE_INSTALL:-0}" != "1" ]]; then
  docker_progress 75 "Docker 인터넷 비상 설치(핀 버전)…"
  (
    pct=75
    while [[ $pct -le 90 ]]; do
      docker_progress "$pct" "Docker CE 비상 apt… (${pct}%)"
      sleep 2
      pct=$((pct + 1))
    done
  ) &
  ONLINE_TICK_PID=$!
  if timeout "${WHICK_ONLINE_INSTALL_TIMEOUT:-300}" bash -c "source '$SCRIPT_DIR/whick-dual-install-common.sh' && try_online_docker_ce"; then
    kill "$ONLINE_TICK_PID" 2>/dev/null || true
    wait "$ONLINE_TICK_PID" 2>/dev/null || true
    finish_ok "internet-emergency"
  fi
  kill "$ONLINE_TICK_PID" 2>/dev/null || true
  wait "$ONLINE_TICK_PID" 2>/dev/null || true
  dpkg --configure -a 2>/dev/null || true
  apt-get install -y -f --no-install-recommends 2>/dev/null || true
  if docker_ready; then
    finish_ok "internet-emergency-repair"
  fi
  log "internet emergency failed — giving up"
fi

log "ERROR: Docker not installed — CC and internet emergency both failed"
exit 1
