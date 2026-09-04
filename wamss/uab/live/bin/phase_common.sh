#!/usr/bin/env bash
# Shared helpers for UAB phases 5~7
set -euo pipefail

UAB_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PHASE_DIR="${WHICK_PHASE_DIR:-/tmp/whick-phases}"
mkdir -p "$PHASE_DIR"

# whick-disk.env defaults — caller export( lab / prod ) wins over file
_saved_install_reserve="${WHICK_INSTALL_RESERVE_GB:-}"
_saved_music_min="${WHICK_MUSIC_MIN_GB:-}"
_saved_install_min="${WHICK_INSTALL_MIN_GB:-}"
if [[ -f "$UAB_ROOT/lib/whick-disk.env" ]]; then
  # shellcheck source=/dev/null
  set -a
  . "$UAB_ROOT/lib/whick-disk.env"
  set +a
fi
if [[ -n "$_saved_install_reserve" ]]; then export WHICK_INSTALL_RESERVE_GB="$_saved_install_reserve"; fi
if [[ -n "$_saved_music_min" ]]; then export WHICK_MUSIC_MIN_GB="$_saved_music_min"; fi
if [[ -n "$_saved_install_min" ]]; then export WHICK_INSTALL_MIN_GB="$_saved_install_min"; fi

# WHICK_INSTALL_RESERVE_GB — 명시(랩 테스트 등)한 경우에만 export한다.
# 기본값을 강제로 채우지 않아야 disk_plan.py의 root 이원화
# (128G 미만 32G / 128G 이상 64G)가 그대로 적용된다.
if [[ -n "${WHICK_INSTALL_RESERVE_GB:-}" ]]; then export WHICK_INSTALL_RESERVE_GB; fi
export WHICK_MUSIC_LABEL="${WHICK_MUSIC_LABEL:-whick-music}"
export WHICK_MUSIC_MOUNT="${WHICK_MUSIC_MOUNT:-/mnt/music}"

phase_log() {
  echo "[phase] $*"
}

phase_progress() {
  local phase="$1" pct="$2" msg="$3"
  phase_log "$phase $pct% — $msg"
  python3 "$UAB_ROOT/bin/cc_progress.py" --phase "$phase" --pct "$pct" --msg "$msg" 2>/dev/null || true
}

phase_failed() {
  local msg="$1"
  local fail_log="${WHICK_INSTALL_FAIL_LOG:-/var/log/whick-install-fail.log}"
  local phase_fail="$PHASE_DIR/last_fail.log"
  mkdir -p "$(dirname "$fail_log")" "$PHASE_DIR" 2>/dev/null || true
  {
    echo "=== $(date -Is 2>/dev/null || date) phase_failed ==="
    echo "msg=$msg"
    echo "phase_dir=$PHASE_DIR"
    echo "host=$(hostname 2>/dev/null || echo unknown)"
  } | tee -a "$fail_log" "$phase_fail" >&2
  phase_progress failed 0 "$msg"
  touch "$PHASE_DIR/install_failed"
  exit 1
}

# Run install script with tee + fail-fast. Optional UI tick; real failure stops the phase.
# Usage: phase_run_script <phase> <tick_start> <tick_end> <tick_msg> <script_path>
# Env:
#   WHICK_PHASE_SCRIPT_TIMEOUT — overall seconds (0=off). Docker should set ~420.
#   WHICK_PHASE_TICK — 0 disables background tick (real script messages show on CC).
phase_run_script() {
  local phase="$1" t0="$2" t1="$3" tmsg="$4" script="$5"
  local logf="$PHASE_DIR/${phase}.run.log"
  local fail_log="${WHICK_INSTALL_FAIL_LOG:-/var/log/whick-install-fail.log}"
  local tick_pid="" rc=0
  local limit="${WHICK_PHASE_SCRIPT_TIMEOUT:-0}"
  phase_log "run $script → $logf (timeout=${limit:-0}s tick=${WHICK_PHASE_TICK:-1})"
  if [[ "${WHICK_PHASE_TICK:-1}" != "0" && "$t0" -le "$t1" ]]; then
    tick_pid="$(phase_tick "$phase" "$t0" "$t1" "$tmsg" 1)"
  fi
  set +e
  if [[ "$limit" =~ ^[1-9][0-9]*$ ]]; then
    # Kill whole script tree if hung (apt/dpkg/fetch).
    timeout --foreground -k 20 "$limit" bash "$script" 2>&1 | tee -a "$logf"
    rc=${PIPESTATUS[0]}
    # timeout exit 124
    if [[ "$rc" -eq 124 ]]; then
      echo "[phase] $phase HARD TIMEOUT after ${limit}s" | tee -a "$logf" >&2
    fi
  else
    bash "$script" 2>&1 | tee -a "$logf"
    rc=${PIPESTATUS[0]}
  fi
  set -e
  if [[ -n "$tick_pid" ]]; then
    kill "$tick_pid" 2>/dev/null || true
    wait "$tick_pid" 2>/dev/null || true
  fi
  if [[ "$rc" -ne 0 ]]; then
    local tail
    tail="$(tail -n 20 "$logf" 2>/dev/null | tr '\n' ' ' | sed 's/  */ /g')"
    mkdir -p "$(dirname "$fail_log")" 2>/dev/null || true
    {
      echo "=== $(date -Is 2>/dev/null || date) phase=$phase script=$script rc=$rc ==="
      tail -n 50 "$logf" 2>/dev/null || true
      echo
    } >>"$fail_log" 2>/dev/null || true
    if [[ "$rc" -eq 124 ]]; then
      phase_failed "${phase} HARD TIMEOUT (${limit}s)${tail:+: ${tail}}"
    fi
    phase_failed "${phase} 실패 (exit $rc)${tail:+: ${tail}}"
  fi
}

# Background progress ticker — bounded. After end_pct, optional short heartbeat then STOP
# so real install messages are not permanently masked by working… N.
# Usage: phase_tick "<phase>" <start_pct> <end_pct> "<msg>" [<sleep_sec>] [<max_working>]
phase_tick() {
  local phase="$1" start_pct="$2" end_pct="$3" msg="$4" sleep_sec="${5:-2}" max_working="${6:-45}"
  (
    local pct="$start_pct"
    while [[ "$pct" -le "$end_pct" ]]; do
      sleep "$sleep_sec"
      python3 "$UAB_ROOT/bin/cc_progress.py" --phase "$phase" --pct "$pct" --msg "${msg} (${pct}%)" 2>/dev/null || true
      pct=$((pct + 1))
    done
    local hold="$end_pct" n=0
    while [[ "$n" -lt "$max_working" ]]; do
      sleep "$sleep_sec"
      n=$((n + 1))
      python3 "$UAB_ROOT/bin/cc_progress.py" --phase "$phase" --pct "$hold" \
        --msg "${msg} (working… ${n})" 2>/dev/null || true
    done
  ) &
  echo $!
}
