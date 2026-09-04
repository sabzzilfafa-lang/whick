#!/usr/bin/env bash
# Live USB — DHCP/WAN 확인 (유선·provision STA). 가상 AP 없음.
set -euo pipefail

log() { echo "[network-setup] $*"; }

if command -v nmcli >/dev/null; then
  nmcli networking on 2>/dev/null || true
  nmcli device status 2>/dev/null || true
  for dev in eth0 enp* wlan0 wlp*; do
    if ip link show "$dev" &>/dev/null; then
      nmcli device connect "$dev" 2>/dev/null && log "connected $dev" && break
    fi
  done
fi

if curl -sf --max-time 5 https://admin.whick.org/api/v1/system/health >/dev/null 2>&1; then
  log "WAN OK (admin.whick.org)"
  exit 0
fi

log "WARN: WAN 미확인 — 유선 링크 또는 provision Wi-Fi(STA) 확인"
exit 0
