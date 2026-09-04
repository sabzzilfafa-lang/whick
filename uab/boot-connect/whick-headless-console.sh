#!/bin/sh
# Headless install — no monitor/keyboard login (smartphone only)
WHICK_HEADLESS_TTY="${WHICK_SETUP_TTY:-/dev/tty1}"

whick_disable_console_login() {
  if [ -f /run/whick-getty-disabled ]; then
    pkill -f '/sbin/getty' 2>/dev/null || true
    pkill -f 'agetty' 2>/dev/null || true
    return 0
  fi
  pkill -f '/sbin/getty' 2>/dev/null || true
  pkill -f 'agetty' 2>/dev/null || true
  pkill -f 'getty.*tty' 2>/dev/null || true
  if [ -x /sbin/rc-service ]; then
    for svc in agetty.tty1 agetty.tty2 agetty.tty3 agetty.tty4 agetty.tty5 agetty.tty6; do
      rc-service "$svc" stop 2>/dev/null || true
      rc-update del "$svc" default boot sysinit 2>/dev/null || true
    done
  fi
  if [ -f /etc/inittab ]; then
    sed -i 's/^\(tty[0-9].*getty\)/#\1/' /etc/inittab 2>/dev/null || true
    sed -i 's/^\(ttyS.*getty\)/#\1/' /etc/inittab 2>/dev/null || true
    kill -HUP 1 2>/dev/null || true
  fi
  touch /run/whick-getty-disabled 2>/dev/null || true
}

whick_headless_banner() {
  # Python whick-customer-setup.py (tty_status_loop) owns tty1 after handoff
  if [ -f /run/whick-tty-handoff ]; then
    return 0
  fi
  _tty="${1:-$WHICK_HEADLESS_TTY}"
  {
    echo ""
    echo "  Whick Music Server"
    echo "  =================="
    echo "  Monitor/keyboard NOT required."
    echo "  Use your smartphone on the same network (Wi-Fi or LAN)."
    echo ""
    if [ -f /tmp/whick-setup-state.json ] && command -v python3 >/dev/null 2>&1; then
      python3 - <<'PY' 2>/dev/null || true
import json
from pathlib import Path
try:
    st = json.loads(Path("/tmp/whick-setup-state.json").read_text())
except Exception:
    st = {}
msg = (st.get("progress_msg") or "").strip()
code = (st.get("device_code") or "").strip()
phase = (st.get("phase") or "").strip()
if code:
    print(f"  Device: {code}")
if msg:
    print(f"  {msg}")
elif phase:
    print(f"  Phase: {phase}")
else:
    print("  Setup starting…")
PY
    else
      echo "  Setup starting…"
    fi
    echo ""
  } >"$_tty" 2>/dev/null || true
}
