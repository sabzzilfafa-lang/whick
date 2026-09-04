#!/usr/bin/env bash
# Shared step OK/FAIL logging for install_linux / install_docker / install_runtime.
# Source from phase scripts or bin/install-*.sh (does not force set -e).
#
# Env:
#   WHICK_INSTALL_FAIL_LOG  — central fail journal (default /var/log/whick-install-fail.log)
#   WHICK_INSTALL_PHASE     — phase name for log lines (install_docker, …)

WHICK_INSTALL_FAIL_LOG="${WHICK_INSTALL_FAIL_LOG:-/var/log/whick-install-fail.log}"
WHICK_INSTALL_PHASE="${WHICK_INSTALL_PHASE:-unknown}"

_whick_install_mkdir_log() {
  mkdir -p "$(dirname "$WHICK_INSTALL_FAIL_LOG")" 2>/dev/null || true
}

whick_step_ok() {
  local step="$1"
  shift
  local msg="${*:-}"
  local line="[OK] $(date -Is 2>/dev/null || date) phase=${WHICK_INSTALL_PHASE} step=${step}${msg:+ ${msg}}"
  echo "$line"
}

whick_step_fail() {
  local step="$1"
  shift
  local msg="${*:-failed}"
  local line="[FAIL] $(date -Is 2>/dev/null || date) phase=${WHICK_INSTALL_PHASE} step=${step} ${msg}"
  _whick_install_mkdir_log
  echo "$line" | tee -a "$WHICK_INSTALL_FAIL_LOG" >&2
  return 1
}

# Log failure and exit 1 (for bin/install-*.sh).
# Optional: define whick_on_step_fail() before calling (e.g. CC progress).
whick_fail_exit() {
  local step="$1"
  shift
  local msg="${*:-failed}"
  whick_step_fail "$step" "$msg" || true
  if declare -F whick_on_step_fail >/dev/null 2>&1; then
    whick_on_step_fail "$step" "$msg" || true
  fi
  exit 1
}

whick_append_fail_block() {
  local title="$1"
  shift
  _whick_install_mkdir_log
  {
    echo "=== $(date -Is 2>/dev/null || date) $title ==="
    if [[ "$#" -gt 0 ]]; then
      printf '%s\n' "$@"
    else
      cat
    fi
    echo
  } >>"$WHICK_INSTALL_FAIL_LOG" 2>/dev/null || true
}
