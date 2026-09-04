#!/bin/sh
# 호스트 워치독 설치 — agent 컨테이너 밖(호스트)에서 sudo로 실행.
# systemd가 있으면 timer(1분), 없으면 cron(1분)로 등록한다.
#   sudo sh install-watchdog.sh
set -eu

SRC_DIR="$(cd "$(dirname "$0")" && pwd)"
WD="/usr/local/sbin/whick-agent-watchdog.sh"

echo "== install watchdog script =="
install -m 0755 "$SRC_DIR/whick-agent-watchdog.sh" "$WD"

if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
  echo "== systemd timer =="
  install -m 0644 "$SRC_DIR/whick-agent-watchdog.service" /etc/systemd/system/whick-agent-watchdog.service
  install -m 0644 "$SRC_DIR/whick-agent-watchdog.timer" /etc/systemd/system/whick-agent-watchdog.timer
  systemctl daemon-reload
  systemctl enable --now whick-agent-watchdog.timer
  systemctl status --no-pager whick-agent-watchdog.timer 2>/dev/null | head -5 || true
else
  echo "== cron (no systemd) =="
  LINE="* * * * * $WD >/var/log/whick-watchdog.log 2>&1"
  ( crontab -l 2>/dev/null | grep -v 'whick-agent-watchdog.sh' || true; echo "$LINE" ) | crontab -
  echo "cron installed: $LINE"
fi

echo "== done — watchdog active (heartbeat stale → restart agent → reboot) =="
