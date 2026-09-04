#!/usr/bin/env bash
# Phase 5 — Linux SSD install (curtin or disk_plan + parted)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=/dev/null
. "$ROOT/bin/phase_common.sh"
# shellcheck source=/dev/null
. "$ROOT/lib/bootstrap_tar_check.sh"

PLAN_JSON="$PHASE_DIR/disk_plan.json"
CURTIN_CFG="$PHASE_DIR/whick-curtin.cfg"
PLAN_ERR="$PHASE_DIR/disk_plan.err"
PLAN_EXTRA_JSON="$PHASE_DIR/disk_plan_extra.json"

export WHICK_INSTALL_PHASE=install_linux
phase_progress install_linux 0 "디스크 확인 중…"

phase_log "storage drivers + lsblk"
for mod in nvme nvme_core ahci libata scsi_mod sd_mod; do
  modprobe "$mod" 2>/dev/null || true
done
if command -v mdev >/dev/null 2>&1; then
  mdev -s 2>/dev/null || true
fi
sleep 1

phase_progress install_linux 3 "스토리지 드라이버 로드 완료"

if command -v lsblk >/dev/null 2>&1; then
  lsblk -d -o NAME,PATH,SIZE,RM,TRAN,TYPE 2>/dev/null | while read -r line; do phase_log "lsblk: $line"; done
else
  phase_log "WARN: lsblk missing — rebuild USB with lsblk apk"
fi

phase_progress install_linux 6 "디스크 파티션 계획 중…"

if [[ "${WHICK_PROD_INSTALL:-0}" == "1" && "${WHICK_LINUX_INSTALL_DRY_RUN:-0}" == "1" ]]; then
  phase_failed "prod USB cannot run dry-run — WHICK_PROD_INSTALL=1 requires real disk apply"
fi

_plan_ok=0
for attempt in 1 2 3; do
  if python3 "$ROOT/bin/disk_plan.py" --plan -o "$PLAN_JSON" 2>"$PLAN_ERR"; then
    _plan_ok=1
    break
  fi
  phase_log "disk plan attempt $attempt failed — rescan block devices"
  for mod in nvme nvme_core ahci libata sd_mod; do
    modprobe "$mod" 2>/dev/null || true
  done
  sleep 2
done
if [[ "$_plan_ok" -ne 1 ]]; then
  err="$(tail -n 5 "$PLAN_ERR" 2>/dev/null | tr '\n' ' ' | sed 's/  */ /g')"
  phase_failed "disk plan failed${err:+: ${err}}"
fi

phase_log "disk plan:"
cat "$PLAN_JSON"

# Music partition must never appear in wipe list incorrectly — sanity check
if python3 - <<'PY' "$PLAN_JSON"
import json, sys
plan = json.load(open(sys.argv[1]))
preserve = {p["path"] for p in plan.get("preserve", [])}
for w in plan.get("wipe", []):
    if w in preserve:
        print(f"FATAL: music partition {w} in wipe list", file=sys.stderr)
        sys.exit(1)
PY
then
  phase_log "preserve/wipe sanity OK"
else
  phase_failed "music partition would be wiped"
fi

# 2번째 이상 SSD — 헤드리스 설치라 고객이 고를 방법이 없어 전량 /mnt/music/diskN 편입.
# 실패해도 본 설치는 계속(추가 저장공간은 보너스 — 없어도 설치 자체는 성립).
if python3 "$ROOT/bin/disk_plan.py" --plan-extra -o "$PLAN_EXTRA_JSON" 2>>"$PLAN_ERR"; then
  if python3 - <<'PY' "$PLAN_EXTRA_JSON"
import json, sys
plans = json.load(open(sys.argv[1]))
for plan in plans:
    preserve = {p["path"] for p in plan.get("preserve", [])}
    for w in plan.get("wipe", []):
        if w in preserve:
            print(f"FATAL: extra music partition {w} in wipe list", file=sys.stderr)
            sys.exit(1)
PY
  then
    phase_log "extra disk plan: $(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1]))))' "$PLAN_EXTRA_JSON") disk(s)"
  else
    phase_log "WARN: extra disk plan sanity failed — skip extra disk(s)"
    echo '[]' >"$PLAN_EXTRA_JSON"
  fi
else
  phase_log "WARN: extra disk plan failed (no 2nd SSD or lsblk issue) — skip extra disk(s)"
  echo '[]' >"$PLAN_EXTRA_JSON"
fi

phase_progress install_linux 10 "파티션 계획 완료"

if [[ "${WHICK_LINUX_INSTALL_DRY_RUN:-0}" == "1" ]]; then
  phase_log "WHICK_LINUX_INSTALL_DRY_RUN=1 — skip destructive install"
  phase_progress install_linux 100 "linux install dry-run OK"
  touch "$PHASE_DIR/linux_install_done"
  exit 0
fi

# USB Live — SSD 확정·reboot 전 parted 금지 (whick-customer-setup 기본 dry-run)
if [[ "${WHICK_USB_LIVE_INSTALL:-0}" == "1" && "${WHICK_ALLOW_LIVE_DISK_APPLY:-0}" != "1" ]]; then
  phase_failed "USB Live에서는 파티션 적용 불가 — WHICK_LINUX_INSTALL_DRY_RUN=1 또는 SSD 부팅 후 재시도"
fi

phase_progress install_linux 15 "파티션 적용 준비 완료"

bootstrap_cc_fetch_possible() {
  [[ "${WHICK_DEPLOY_NO_CC_FETCH:-0}" == "1" ]] && return 1
  for p in "${WHICK_BOOTSTRAP_SESSION:-}" /tmp/whick-bootstrap-session.json; do
    [[ -n "$p" && -f "$p" ]] && return 0
  done
  return 1
}

if [[ "${WHICK_PROD_INSTALL:-0}" == "1" ]]; then
  _boot=""
  for candidate in \
    "${WHICK_BOOTSTRAP_ROOTFS:-}" \
    "/opt/whick-boot-connect/bootstrap/whick-bootstrap-rootfs.tar.xz" \
    "${WHICK_USB_ROOT:-}/whick-boot-connect/bootstrap/whick-bootstrap-rootfs.tar.xz" \
    "/data/whick-ai_music_server/3_product/dist/uab/whick-bootstrap-rootfs.tar.xz"; do
    if [[ -n "$candidate" && -f "$candidate" ]] && bootstrap_tar_boot_ready "$candidate"; then
      _boot="$candidate"
      export WHICK_BOOTSTRAP_ROOTFS="$candidate"
      break
    fi
    if [[ -n "$candidate" && -f "$candidate" ]]; then
      phase_log "WARN: skipping bootstrap not boot-ready (need initrd+vmlinuz): $candidate"
    fi
  done
  if [[ -z "$_boot" ]]; then
    if bootstrap_cc_fetch_possible; then
      phase_log "WARN: no local boot-ready bootstrap — CC fetch after partition apply"
      unset WHICK_BOOTSTRAP_ROOTFS
    else
      phase_failed "prod install: boot-ready bootstrap missing (initrd+vmlinuz tarball or bootstrap session for CC fetch)"
    fi
  else
    phase_log "bootstrap rootfs: $_boot"
  fi
fi

if command -v curtin >/dev/null 2>&1 && [[ -x "$ROOT/curtin/generate-curtin-config.py" ]]; then
  phase_progress install_linux 20 "curtin 설정 생성…"
  python3 "$ROOT/curtin/generate-curtin-config.py" "$PLAN_JSON" >"$CURTIN_CFG"
  phase_progress install_linux 30 "Ubuntu 설치 중…"
  # Background tick 30→89 during curtin install
  CURTIN_TICK_PID=$(phase_tick install_linux 31 89 "Ubuntu 설치 중" 2)
  set +e
  curtin install -c "$CURTIN_CFG"
  curtin_rc=$?
  set -e
  kill "$CURTIN_TICK_PID" 2>/dev/null || true
  wait "$CURTIN_TICK_PID" 2>/dev/null || true
  if [[ "$curtin_rc" -ne 0 ]]; then
    phase_failed "curtin install failed (exit $curtin_rc)"
  fi
  phase_progress install_linux 90 "부트로더 설정…"
  set +e
  curtin finalize
  finalize_rc=$?
  set -e
  if [[ "$finalize_rc" -ne 0 ]]; then
    phase_failed "curtin finalize failed (exit $finalize_rc)"
  fi
else
  SKIP_PART=0
  if [[ "${WHICK_INSTALL_RETRY:-0}" == "1" ]] && blkid -L whick-root >/dev/null 2>&1; then
    phase_log "retry: whick-root already present — skip re-partition (resume deploy)"
    SKIP_PART=1
    phase_progress install_linux 40 "재시도 — 기존 파티션 유지, rootfs 이어서…"
  fi
  if [[ "$SKIP_PART" -ne 1 ]]; then
    phase_progress install_linux 30 "파티션 적용 (parted)…"
    if ! WHICK_DISK_APPLY=1 python3 "$ROOT/bin/disk_plan.py" --apply --plan-file "$PLAN_JSON" 2>>"$PLAN_ERR"; then
      err="$(tail -n 8 "$PLAN_ERR" 2>/dev/null | tr '\n' ' ' | sed 's/  */ /g')"
      phase_failed "partition apply failed${err:+: ${err}}"
    fi
    phase_progress install_linux 40 "파티션 적용 완료"

    # 2번째 이상 SSD 적용 — 실패해도 본 설치는 계속(추가 저장공간은 보너스)
    if [[ -s "$PLAN_EXTRA_JSON" && "$(cat "$PLAN_EXTRA_JSON")" != "[]" ]]; then
      if ! WHICK_DISK_APPLY=1 python3 "$ROOT/bin/disk_plan.py" --apply-extra --plan-file "$PLAN_EXTRA_JSON" 2>>"$PLAN_ERR"; then
        err="$(tail -n 8 "$PLAN_ERR" 2>/dev/null | tr '\n' ' ' | sed 's/  */ /g')"
        phase_log "WARN: extra disk apply failed${err:+: ${err}} — continuing without extra /mnt/music/diskN"
        echo '[]' >"$PLAN_EXTRA_JSON"
      else
        phase_log "extra disk(s) applied -> /mnt/music/diskN"
      fi
    fi
  fi
  if [[ "${WHICK_PROD_INSTALL:-0}" == "1" || -n "${WHICK_BOOTSTRAP_ROOTFS:-}" ]]; then
    phase_progress install_linux 50 "Deploying Ubuntu rootfs..."
    DEPLOY_LOG="$PHASE_DIR/deploy_bootstrap.log"
    # No background tick — Jul22 success path used real steps only.
    # Fake tick (51→88) raced real progress and looked frozen at ~87%.
    set +e
    bash "$ROOT/bin/deploy_bootstrap_rootfs.sh" "$PLAN_JSON" "$PLAN_EXTRA_JSON" 2>>"$PLAN_ERR" | tee "$DEPLOY_LOG"
    deploy_rc=${PIPESTATUS[0]}
    set -e
    if [[ "$deploy_rc" -ne 0 ]]; then
      err="$(grep -E '\[deploy_bootstrap\] (ERROR|FATAL)|ERROR |FATAL:' "$DEPLOY_LOG" "$PLAN_ERR" 2>/dev/null | tail -n 3 | tr '\n' ' ' | sed 's/  */ /g')"
      if [[ -z "$err" ]]; then
        err="$(tail -n 20 "$PLAN_ERR" 2>/dev/null | tr '\n' ' ' | sed 's/  */ /g')"
      fi
      # Prefer real mount/busy failures — do NOT match progress "EFI mounted" (masks FATAL).
      busy="$(grep -E 'Resource busy|mount failed|ERROR mount|partition in use|parted blocked|parted timeout|no filesystem|HINT:' "$PLAN_ERR" "$DEPLOY_LOG" 2>/dev/null | tail -n 2 | tr '\n' ' ' | sed 's/  */ /g')"
      if [[ -n "$busy" && ( -z "$err" || "$busy" == *"Resource busy"* || "$busy" == *"mount failed"* ) ]]; then
        err="$busy"
      fi
      mkdir -p "$(dirname "${WHICK_INSTALL_FAIL_LOG:-/var/log/whick-install-fail.log}")" 2>/dev/null || true
      {
        echo "=== $(date -Is 2>/dev/null || date) install_linux deploy_bootstrap failed rc=$deploy_rc ==="
        tail -n 80 "$DEPLOY_LOG" 2>/dev/null || true
        tail -n 40 "$PLAN_ERR" 2>/dev/null || true
        echo
      } >>"${WHICK_INSTALL_FAIL_LOG:-/var/log/whick-install-fail.log}" 2>/dev/null || true
      phase_failed "Ubuntu rootfs deploy failed${err:+: ${err}}"
    fi
    phase_log "[OK] step=deploy_bootstrap Ubuntu rootfs + GRUB"
    phase_progress install_linux 89 "Ubuntu rootfs + GRUB done"
    if [[ -f "$DEPLOY_LOG" ]]; then
      grep '\[deploy_bootstrap\] INITRD_TELEMETRY' "$DEPLOY_LOG" 2>/dev/null | while read -r line; do
        phase_log "${line#\[deploy_bootstrap\] }"
      done || true
      grep '\[deploy_bootstrap\].*initrd' "$DEPLOY_LOG" 2>/dev/null | tail -3 | while read -r line; do
        phase_log "${line#\[deploy_bootstrap\] }"
      done || true
      grep '\[deploy_bootstrap\] WARN rescue' "$DEPLOY_LOG" 2>/dev/null | while read -r line; do
        phase_log "${line#\[deploy_bootstrap\] }"
      done || true
    fi
  else
    phase_log "WARN: no bootstrap rootfs — partition only (set WHICK_PROD_INSTALL=1)"
    if [[ "${WHICK_PROD_INSTALL:-0}" == "1" ]]; then
      phase_failed "prod install requires Ubuntu rootfs deploy"
    fi
  fi
fi

phase_progress install_linux 90 "Ubuntu SSD deploy complete"
phase_progress install_linux 95 "Verifying install..."
phase_progress install_linux 100 "Linux partition install done"
touch "$PHASE_DIR/linux_install_done"
