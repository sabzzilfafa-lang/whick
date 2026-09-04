#!/bin/sh
# snd-aloop — Camilla 상주 입력(Loopback) 확보
set -eu
LOG="${WHICK_CAMILLA_DAEMON_LOG:-/var/lib/whick/run/camilladsp-daemon.log}"
ASOUND="${WHICK_ASOUND_ROOT:-/proc/asound}"

ts() { date -Iseconds; }
log() { echo "[ensure-aloop] $(ts) $*" | tee -a "$LOG" >&2; }

if [ -f "$ASOUND/cards" ] && grep -q Loopback "$ASOUND/cards" 2>/dev/null; then
  log "Loopback already present"
  exit 0
fi

if ! command -v modprobe >/dev/null 2>&1; then
  log "WARN modprobe missing"
  exit 1
fi

# index=10 — USB DAC(0…)과 충돌 최소화
if modprobe snd-aloop index=10 id=Loopback pcm_substreams=4 2>>"$LOG"; then
  log "modprobe snd-aloop ok"
  exit 0
fi

# 일부 커널은 파라미터 없이만 허용
if modprobe snd-aloop 2>>"$LOG"; then
  log "modprobe snd-aloop (no params) ok"
  exit 0
fi

log "FAIL could not load snd-aloop"
exit 1
