#!/bin/sh
# tty1 — keep getty off; status display is owned by whick-customer-setup.py (tty_status_loop)
ROOT="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=/dev/null
[ -f "$ROOT/whick-headless-console.sh" ] && . "$ROOT/whick-headless-console.sh"

whick_disable_console_login

while true; do
  whick_disable_console_login
  sleep 60
done
