#!/bin/sh
# USB 부팅 — 유선(eth/USB-LAN) 또는 무선 provision STA. 가상 AP 없음.
ROOT="$(cd "$(dirname "$0")" && pwd)"
TTY="${WHICK_SETUP_TTY:-/dev/tty1}"

if [ -f "$ROOT/whick-env.sh" ]; then
  # shellcheck source=/dev/null
  . "$ROOT/whick-env.sh"
fi

if [ -f "$ROOT/whick-kernel-modules.sh" ]; then
  # shellcheck source=/dev/null
  . "$ROOT/whick-kernel-modules.sh"
  _i=0
  while [ "$_i" -lt 30 ]; do
    whick_ensure_modloop 2>/dev/null && break
    sleep 1
    _i=$((_i + 1))
  done
  whick_mount_firmware 2>/dev/null || true
  whick_load_net_modules 2>/dev/null || true
  whick_reload_nic 2>/dev/null || true
  _prof="$(whick_net_profile 2>/dev/null || echo full)"
  if [ "$_prof" = "wired" ]; then
    export WHICK_KERNEL_MODULES_DONE=1
  elif [ "$_prof" = "wireless" ]; then
    for _n in /sys/class/net/*; do
      [ -d "$_n/wireless" ] || continue
      export WHICK_KERNEL_MODULES_DONE=1
      break
    done
  else
    for _n in /sys/class/net/*; do
      [ -d "$_n/wireless" ] || continue
      export WHICK_KERNEL_MODULES_DONE=1
      break
    done
  fi
fi

msg() {
  printf '%s\n' "$*" >"$TTY" 2>/dev/null || printf '%s\n' "$*"
}

if [ -f "$ROOT/whick-headless-console.sh" ]; then
  # shellcheck source=/dev/null
  . "$ROOT/whick-headless-console.sh"
  whick_disable_console_login
fi

pkill -f '/sbin/getty' 2>/dev/null || true
pkill -f 'agetty' 2>/dev/null || true
pkill -f 'getty.*tty1' 2>/dev/null || true
export WHICK_SETUP_TTY="${WHICK_SETUP_TTY:-/dev/tty1}"
msg ""
msg "  Whick Music Server"
msg "  Starting setup server…"
msg "  (instructions update when network is ready)"
msg ""

if ! command -v python3 >/dev/null 2>&1; then
  msg "  ERROR: python3 not found"
  exit 1
fi
exec python3 "$ROOT/whick-customer-setup.py"
