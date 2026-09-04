#!/bin/sh
# Whick 호스트 워치독 — agent 컨테이너와 독립적으로 동작.
# agent가 CC로 heartbeat를 못 보내는 상태(hang·네트워크 wedge)를 감지하고
# agent 재시작 → (회복 안 되면) 호스트 재부팅으로 자동 복구한다.
# 고객은 "전원만으로 복구"가 자동화되는 것이 목표.
#
# 설치: install-watchdog.sh (systemd timer 1분 간격)
# 수동: sh whick-agent-watchdog.sh
set -eu

CC_URL="${WHICK_CC_API_URL:-https://admin.whick.org/api/v1}"
CC_HEALTH="${CC_URL%/}/system/health"
PROJECT="${WHICK_COMPOSE_PROJECT:-whick-runtime}"
DATA_VOLUME="${WHICK_DATA_VOLUME:-${PROJECT}_whick-data}"
STATE_FILE="/var/lib/whick/agent-watchdog.state"
# dev_pull·재빌드 중에는 agent가 의도적으로 내려가므로 워치독 개입을 멈춘다.
UPDATE_SENTINEL="${WHICK_UPDATE_SENTINEL:-/var/lib/whick/.update-in-progress}"
UPDATE_SENTINEL_MAX_AGE="${WHICK_UPDATE_SENTINEL_MAX_AGE:-1800}"
LOG_TAG="whick-watchdog"

# 임계값 (초)
HB_STALE_SEC="${WHICK_WD_HB_STALE_SEC:-180}"      # heartbeat 이보다 오래되면 이상
REBOOT_GRACE_SEC="${WHICK_WD_REBOOT_GRACE_SEC:-300}"  # 재시작 후에도 이만큼 더 끊기면 재부팅
# 네트워크/CC 상태와 무관하게 이만큼 stale면 강제 재부팅 — NIC wedge 등 어떤 원인이든 자동복구.
HB_HARD_REBOOT_SEC="${WHICK_WD_HB_HARD_REBOOT_SEC:-360}"
REBOOT_COOLDOWN_SEC="${WHICK_WD_REBOOT_COOLDOWN_SEC:-1800}"  # 재부팅 최소 간격(루프 방지)
NET_TIMEOUT="${WHICK_WD_NET_TIMEOUT:-10}"

log() { logger -t "$LOG_TAG" "$*" 2>/dev/null || true; echo "[$LOG_TAG] $*"; }

now() { date +%s; }

# --- state helpers (key=value) ---
state_get() { [ -f "$STATE_FILE" ] && awk -F= -v k="$1" '$1==k{print $2; exit}' "$STATE_FILE" || true; }
state_set() {
  mkdir -p "$(dirname "$STATE_FILE")"
  tmp="${STATE_FILE}.tmp"
  { [ -f "$STATE_FILE" ] && grep -v "^$1=" "$STATE_FILE" || true; echo "$1=$2"; } >"$tmp" 2>/dev/null || true
  mv "$tmp" "$STATE_FILE" 2>/dev/null || true
}

# --- agent heartbeat 시각(runtime-state.json mtime) ---
heartbeat_age_sec() {
  mp="$(timeout "$NET_TIMEOUT" docker volume inspect "$DATA_VOLUME" --format '{{.Mountpoint}}' 2>/dev/null || true)"
  [ -z "$mp" ] && { echo -1; return; }
  f="$mp/runtime-state.json"
  [ -f "$f" ] || { echo -1; return; }
  mt="$(stat -c %Y "$f" 2>/dev/null || echo 0)"
  [ "$mt" -gt 0 ] 2>/dev/null || { echo -1; return; }
  echo $(( $(now) - mt ))
}

# 0=reachable, 1=unreachable, 2=프로브 도구 없음(판정불가)
reachable() {
  if command -v curl >/dev/null 2>&1; then
    timeout "$NET_TIMEOUT" curl -fsS4 -o /dev/null --max-time "$NET_TIMEOUT" "$1" 2>/dev/null && return 0 || return 1
  fi
  if command -v wget >/dev/null 2>&1; then
    timeout "$NET_TIMEOUT" wget -q -O /dev/null -T "$NET_TIMEOUT" "$1" 2>/dev/null && return 0 || return 1
  fi
  return 2
}

# 0=up, 1=down, 2=판정불가(프로브 도구 없음 → 재부팅 에스컬레이션 금지)
internet_up() {
  for host in "https://1.1.1.1" "https://dns.google"; do
    reachable "$host"; rc=$?
    [ "$rc" -eq 0 ] && return 0
    [ "$rc" -eq 2 ] && return 2
  done
  # 도구는 있으나 둘 다 실패 시: ping 폴백
  if command -v ping >/dev/null 2>&1; then
    timeout "$NET_TIMEOUT" ping -c1 -W "$NET_TIMEOUT" 1.1.1.1 >/dev/null 2>&1 && return 0
    return 1
  fi
  return 1
}

restart_agent() {
  log "restarting agent stack (agent audio monitor)"
  for c in whick-agent whick-audio whick-monitor; do
    timeout 60 docker restart "$c" >/dev/null 2>&1 || log "restart $c failed"
  done
}

# OTA 중단(sibling 강제종료 등)으로 docker-socket-proxy만 정지되면
# agent(DOCKER_HOST=tcp://127.0.0.1:2375)가 docker에 접근 못해
# 이후 모든 OTA·재설치가 영구 불가 (2026-08-26 device49 교착).
# agent 심박이 정상이어도 proxy 정지는 여기서 자가복구한다.
ensure_proxy_up() {
  st="$(timeout "$NET_TIMEOUT" docker inspect --format '{{.State.Running}}' whick-docker-proxy 2>/dev/null || echo missing)"
  if [ "$st" = "false" ]; then
    log "whick-docker-proxy stopped → docker start (self-heal)"
    timeout 60 docker start whick-docker-proxy >/dev/null 2>&1 || log "proxy start failed"
  fi
}

do_reboot() {
  last="$(state_get last_reboot)"; last="${last:-0}"
  if [ $(( $(now) - last )) -lt "$REBOOT_COOLDOWN_SEC" ]; then
    log "reboot suppressed (cooldown ${REBOOT_COOLDOWN_SEC}s)"
    return 0
  fi
  state_set last_reboot "$(now)"
  log "REBOOT — agent unrecoverable; restarting host"
  ( sleep 2; /sbin/reboot || reboot ) >/dev/null 2>&1 &
}

update_in_progress() {
  # docker 볼륨 내부 센티넬(에이전트/업데이트 sibling이 생성)도 확인
  for f in "$UPDATE_SENTINEL" "$(volume_sentinel)"; do
    [ -n "$f" ] && [ -f "$f" ] || continue
    mt="$(stat -c %Y "$f" 2>/dev/null || echo 0)"
    [ "$mt" -gt 0 ] 2>/dev/null || continue
    if [ $(( $(now) - mt )) -lt "$UPDATE_SENTINEL_MAX_AGE" ]; then
      return 0
    fi
  done
  return 1
}

volume_sentinel() {
  mp="$(timeout "$NET_TIMEOUT" docker volume inspect "$DATA_VOLUME" --format '{{.Mountpoint}}' 2>/dev/null || true)"
  [ -n "$mp" ] && echo "$mp/.update-in-progress" || echo ""
}

main() {
  if update_in_progress; then
    log "update in progress — watchdog standby"
    return 0
  fi

  ensure_proxy_up

  age="$(heartbeat_age_sec)"

  # heartbeat 정상 → 이상 카운터 리셋
  if [ "$age" -ge 0 ] 2>/dev/null && [ "$age" -lt "$HB_STALE_SEC" ]; then
    state_set first_bad 0
    state_set restarted 0
    return 0
  fi

  # heartbeat stale (또는 파일 없음)
  log "heartbeat stale age=${age}s (threshold ${HB_STALE_SEC}s)"

  first_bad="$(state_get first_bad)"; first_bad="${first_bad:-0}"
  if [ "$first_bad" -eq 0 ] 2>/dev/null; then
    first_bad="$(now)"; state_set first_bad "$first_bad"
  fi
  bad_for=$(( $(now) - first_bad ))

  # 최우선 안전장치: 어떤 네트워크/CC 판정과도 무관하게 오래 stale면 강제 재부팅.
  # (NIC wedge처럼 host는 ICMP가 되는데 agent heartbeat만 영구히 안 도는 경우까지 자동복구)
  if [ "$bad_for" -ge "$HB_HARD_REBOOT_SEC" ]; then
    log "heartbeat stale ${bad_for}s ≥ hard ${HB_HARD_REBOOT_SEC}s → force reboot"
    do_reboot
    return 0
  fi

  reachable "$CC_HEALTH"; cc_rc=$?
  internet_up; net_rc=$?

  # 프로브 도구(curl/wget/ping) 부재로 판정 불가 → 안전하게 agent 재시작만, 재부팅 금지
  if [ "$net_rc" -eq 2 ]; then
    log "network probe unavailable (no curl/wget/ping) → restart agent only (no reboot)"
    restart_agent
    state_set restarted "$(now)"
    return 0
  fi

  cc_ok=0; [ "$cc_rc" -eq 0 ] && cc_ok=1
  net_ok=0; [ "$net_rc" -eq 0 ] && net_ok=1

  # CC는 호스트에서 닿는데 agent만 멈춤 → agent 재시작
  # 인터넷 자체가 끊김 → 네트워크 wedge(예: speedtest 이후) → agent 재시작 시도 후 재부팅
  if [ "$cc_ok" -eq 1 ] && [ "$net_ok" -eq 1 ]; then
    log "network OK but agent heartbeat stale → restart agent"
    restart_agent
    state_set restarted "$(now)"
    return 0
  fi

  if [ "$net_ok" -eq 0 ]; then
    log "internet unreachable from host (network wedged) bad_for=${bad_for}s"
    restarted="$(state_get restarted)"; restarted="${restarted:-0}"
    if [ "$restarted" -eq 0 ] 2>/dev/null; then
      restart_agent
      state_set restarted "$(now)"
      return 0
    fi
    # 재시작했는데도 회복 안 됨 → 재부팅
    if [ "$bad_for" -ge "$REBOOT_GRACE_SEC" ]; then
      do_reboot
    fi
    return 0
  fi

  # 인터넷은 되는데 CC만 안 닿음 → CC측 점검대상 (장비 재부팅은 도움 안 됨)
  log "internet OK but CC unreachable → CC-side issue; no host action"
}

main "$@"
