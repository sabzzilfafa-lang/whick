#!/bin/sh
# Whick setup agent — respawn on crash (local.d must not block OpenRC local)
set -eu

ROOT="$(cd "$(dirname "$0")" && pwd)"
PIDFILE="${WHICK_SETUP_PIDFILE:-/run/whick-setup.pid}"
TTY="${WHICK_SETUP_TTY:-/dev/tty1}"
DELAY="${WHICK_SETUP_RESPAWN_SEC:-15}"

msg() {
  printf '%s\n' "$*" >"$TTY" 2>/dev/null || printf '%s\n' "$*"
}

if [ -f "$ROOT/whick-env.sh" ]; then
  # shellcheck source=/dev/null
  . "$ROOT/whick-env.sh"
fi

printf '%s\n' "$$" >"$PIDFILE" 2>/dev/null || true

while true; do
  "$ROOT/whick-boot-sequence.sh"
  rc=$?
  if [ "$rc" -eq 0 ]; then
    exit 0
  fi
  msg ""
  msg "  Whick setup exited ($rc) — retry in ${DELAY}s"
  msg ""
  sleep "$DELAY"
done
