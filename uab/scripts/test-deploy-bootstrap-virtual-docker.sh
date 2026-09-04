#!/usr/bin/env bash
# deploy_bootstrap_rootfs.sh — loop SSD 가상 검증 (USB Live 시뮬 · ~2분)
# · 깨진 USB bootstrap 거부 (WHICK_BOOTSTRAP_ROOTFS preset)
# · 새 bootstrap tarball 배포 + UEFI/initrd/grub 검증
set -euo pipefail

if [[ -z "${WHICK_DEPLOY_VIRTUAL_IN_DOCKER:-}" ]]; then
  if [[ ! -w /dev/loop-control ]] || [[ "${WHICK_FORCE_DOCKER_VIRTUAL:-0}" == "1" ]]; then
    SANDBOX_HOST="${WHICK_SANDBOX_SCRATCH:-/data/whick-ai/sandbox-scratch}"
    REPO_HOST="$(cd "$(dirname "$0")/../../.." && pwd)"
    echo "==> privileged Docker (host losetup unavailable)"
    exec docker run --rm --privileged \
      -v "$SANDBOX_HOST:$SANDBOX_HOST" \
      -v "$REPO_HOST:$REPO_HOST" \
      -e WHICK_DEPLOY_VIRTUAL_IN_DOCKER=1 \
      -e WHICK_SANDBOX_SCRATCH="$SANDBOX_HOST" \
      ubuntu:24.04 bash -c '
        export DEBIAN_FRONTEND=noninteractive
        apt-get update -qq && apt-get install -y -qq \
          python3 parted e2fsprogs dosfstools grub-efi-amd64-bin grub-pc-bin \
          kpartx util-linux tar xz-utils mount shim-signed \
          initramfs-tools cpio zstd 2>/dev/null
        bash "'"$REPO_HOST"'/3_product/uab/scripts/test-deploy-bootstrap-virtual-docker.sh"
      '
  fi
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LIVE="$ROOT/live"
SANDBOX="${WHICK_SANDBOX_SCRATCH:-/data/whick-ai/sandbox-scratch}"
GOOD="${WHICK_BOOTSTRAP_ROOTFS:-$SANDBOX/bootstrap-build-out/whick-bootstrap-rootfs.tar.xz}"
BROKEN="${WHICK_BOOTSTRAP_BROKEN:-$SANDBOX/bootstrap-cache/whick-bootstrap-broken.tar.xz}"
WORK="$SANDBOX/runs/deploy-bootstrap-virtual-$$"
LOG="$WORK/test.log"
IMG="$WORK/disk.img"
LOOP=""
MNT="$WORK/mnt"

mkdir -p "$WORK" "$MNT" "$SANDBOX/runs"
exec > >(tee -a "$LOG") 2>&1

die() { echo "FAIL: $*" >&2; exit 1; }
ok() { echo "OK $*"; }

bootstrap_tar_boot_ready() {
  python3 - <<'PY' "$1"
import re, sys, tarfile
path = sys.argv[1]
mode = "r:xz" if path.endswith(".xz") else "r:gz"
with tarfile.open(path, mode) as tf:
    names = tf.getnames()
pat_initrd = re.compile(r"(^|/)boot/initrd\.img-[^/]+$")
pat_vmlinuz = re.compile(r"(^|/)boot/vmlinuz-[^/]+$")
if not any(pat_initrd.search(n) for n in names):
    raise SystemExit("bootstrap tar missing boot/initrd.img-*")
if not any(pat_vmlinuz.search(n) for n in names):
    raise SystemExit("bootstrap tar missing boot/vmlinuz-*")
PY
}

cleanup() {
  umount -lf "$MNT/sys/firmware/efi/efivars" 2>/dev/null || true
  umount -lf "$MNT/run" "$MNT/sys" "$MNT/proc" "$MNT/dev" 2>/dev/null || true
  umount -lf "$MNT/boot/efi" 2>/dev/null || true
  umount -lf "$MNT" 2>/dev/null || true
  [[ -n "${LOOP:-}" ]] && losetup -d "$LOOP" 2>/dev/null || true
}
trap cleanup EXIT

[[ -f "$GOOD" ]] || die "good bootstrap missing: $GOOD"
if ! bootstrap_tar_boot_ready "$GOOD"; then
  die "good bootstrap has no versioned initrd in tar"
fi
ok "good bootstrap tarball ($GOOD)"

# broken = old artifact without initrd.img-* (keep a copy when rebuilding)
if [[ ! -f "$BROKEN" ]]; then
  echo "WARN: broken bootstrap copy missing — skip reject test ($BROKEN)"
  SKIP_REJECT=1
else
  if bootstrap_tar_boot_ready "$BROKEN"; then
    die "broken fixture should not contain initrd.img-*"
  fi
  ok "broken bootstrap fixture"
  SKIP_REJECT=0
fi

truncate -s 24G "$IMG"
LOOP="$(losetup -fP --show "$IMG")"
ok "loop $LOOP"

export WHICK_PHASE_DIR="$WORK/phases"
export WHICK_TARGET_DISK="$LOOP"
export WHICK_MUSIC_MIN_GB=10 WHICK_INSTALL_RESERVE_GB=32 WHICK_INSTALL_MIN_GB=16
export WHICK_ALLOW_LIVE_DISK_APPLY=1 WHICK_DISK_APPLY=1 WHICK_USB_LIVE_INSTALL=1 WHICK_LINUX_INSTALL_DRY_RUN=0
export WHICK_MINI="/opt/whick-boot-connect/mini"
mkdir -p "$WHICK_PHASE_DIR"

USB_ROOT="$WORK/usb"
mkdir -p "$USB_ROOT/whick-boot-connect/artifacts"
export WHICK_USB_ROOT="$USB_ROOT"
export WHICK_BOOTSTRAP_SESSION="$WORK/bootstrap-session.json"
cat >"$WHICK_BOOTSTRAP_SESSION" <<'JSON'
{
  "session_id": 1,
  "device_code": "TEST000001",
  "bootstrap_token": "test-token",
  "cc_api_url": "http://172.30.1.71/api/v1"
}
JSON
readarray -t OFFLINE_ARTIFACTS < <(python3 - <<'PY'
import json
from pathlib import Path
lock = json.load(open("/data/whick-ai_music_server/3_product/uab/live/lib/components.lock.json"))
c = lock.get("components", {})
for name in [
    c.get("docker_ce", {}).get("deb_bundle", ""),
    c.get("runtime_bundle", {}).get("file", ""),
]:
    if name:
        print(name)
PY
)
for artifact in "${OFFLINE_ARTIFACTS[@]}"; do
  src=""
  for candidate in \
    "/mnt/music/whick-cc/build-staging/music-01/$artifact" \
    "/mnt/music/whick-cc/build-staging/uab/$artifact" \
    "/data/whick-ai_music_server/3_product/dist/music-01/$artifact"; do
    [[ -f "$candidate" ]] && { src="$candidate"; break; }
  done
  if [[ -n "$src" ]]; then
    ln -sf "$src" "$USB_ROOT/whick-boot-connect/artifacts/$artifact"
    ok "USB offline artifact fixture $artifact"
  else
    echo "WARN: offline artifact fixture missing: $artifact"
  fi
done

python3 "$LIVE/bin/disk_plan.py" --plan --output "$WHICK_PHASE_DIR/disk_plan.json"
WHICK_DISK_APPLY=1 python3 "$LIVE/bin/disk_plan.py" --apply --plan-file "$WHICK_PHASE_DIR/disk_plan.json"

ROOT_PART="$(blkid -L whick-root -o device 2>/dev/null || true)"
EFI_PART="$(blkid -L WHICK-EFI -o device 2>/dev/null || true)"
[[ -z "$EFI_PART" ]] && EFI_PART="$(blkid -L WHICK-EFI -o device 2>/dev/null || blkid -t PARTLABEL=EFI -o device 2>/dev/null || true)"
[[ -z "$ROOT_PART" ]] && ROOT_PART="$(lsblk -ln -o PATH,LABEL "${LOOP}"* 2>/dev/null | awk '$2=="whick-root"{print $1; exit}')"
[[ -z "$EFI_PART" ]] && EFI_PART="$(lsblk -ln -o PATH,LABEL "${LOOP}"* 2>/dev/null | awk '$2=="WHICK-EFI"{print $1; exit}')"
[[ -b "$ROOT_PART" && -b "$EFI_PART" ]] || die "partition labels missing"

if [[ "${SKIP_REJECT:-1}" == "0" ]]; then
  echo "==> reject broken WHICK_BOOTSTRAP_ROOTFS (USB simulation)"
  export WHICK_BOOTSTRAP_ROOTFS="$BROKEN"
  export WHICK_DEPLOY_NO_CC_FETCH=1
  if bash "$LIVE/bin/deploy_bootstrap_rootfs.sh" "$WHICK_PHASE_DIR/disk_plan.json"; then
    die "deploy should reject broken USB bootstrap"
  fi
  ok "broken bootstrap rejected"
fi

echo "==> deploy good bootstrap"
unset WHICK_DEPLOY_NO_CC_FETCH
export WHICK_BOOTSTRAP_ROOTFS="$GOOD"
bash "$LIVE/bin/deploy_bootstrap_rootfs.sh" "$WHICK_PHASE_DIR/disk_plan.json"
# In this glibc lab chroot lsinitramfs works, so the prebuilt is CONFIRMED
# boot-ready (rc=0). Accept either that or the "cannot re-verify → trust prebuilt"
# path (rc=2), but NEVER a regeneration.
grep -Eq '\[deploy_bootstrap\] using (verified )?prebuilt initrd' "$LOG" || \
  die "deploy did not use the prebuilt initrd; Ubuntu lab may mask Alpine initramfs regeneration bug"
grep -q '\[deploy_bootstrap\] INITRD_TELEMETRY decision=prebuilt-verified' "$LOG" || \
  die "deploy initrd telemetry missing prebuilt-verified decision"
if grep -q 'update-initramfs: Generating' "$LOG"; then
  die "deploy regenerated initrd; USB Live path can drop libcrypto.so.3"
fi
if grep -Eq '\[deploy_bootstrap\].*regenerat(ing|ed)' "$LOG"; then
  die "deploy entered a regeneration path; prebuilt must be trusted as-is"
fi

echo "==> verify SSD boot chain"
mount "$ROOT_PART" "$MNT"
mount "$EFI_PART" "$MNT/boot/efi"
ROOT_UUID="$(blkid -s UUID -o value "$ROOT_PART")"
[[ -n "$ROOT_UUID" ]] || die "root UUID missing"
[[ -f "$MNT/boot/grub/grub.cfg" ]] || die "grub.cfg missing"
grep -q "root=UUID=${ROOT_UUID}" "$MNT/boot/grub/grub.cfg" || die "grub.cfg root UUID"
grep -qE '^\s*initrd\s+' "$MNT/boot/grub/grub.cfg" || die "grub.cfg initrd line"
[[ -f "$MNT/boot/efi/EFI/BOOT/BOOTX64.EFI" ]] || [[ -f "$MNT/boot/efi/EFI/ubuntu/shimx64.efi" ]] || die "EFI loader"
[[ -f "$MNT/boot/efi/EFI/BOOT/grub.cfg" ]] || die "EFI stub"
grep -q 'configfile \$prefix/grub.cfg' "$MNT/boot/efi/EFI/BOOT/grub.cfg" || die "EFI configfile chain"
grep -q "search.fs_uuid ${ROOT_UUID}" "$MNT/boot/efi/EFI/BOOT/grub.cfg" || die "EFI search.fs_uuid"
ls "$MNT/boot/initrd"* >/dev/null 2>&1 || die "initrd on disk"
[[ -f "$MNT/boot/initrd.img-7.0.0-14-generic" ]] || ls "$MNT/boot/initrd.img-"* >/dev/null 2>&1 || die "versioned initrd"
for artifact in "${OFFLINE_ARTIFACTS[@]}"; do
  if [[ -f "$USB_ROOT/whick-boot-connect/artifacts/$artifact" ]]; then
    [[ -f "$MNT/var/lib/whick/install-cache/$artifact" ]] || die "offline artifact not staged on SSD: $artifact"
    ok "SSD install-cache has $artifact"
  fi
done
if [[ -f "$USB_ROOT/whick-boot-connect/artifacts/${OFFLINE_ARTIFACTS[0]:-}" ]]; then
  find "$MNT/var/lib/whick/install-cache/docker-debs" -maxdepth 1 -name '*.deb' 2>/dev/null | grep -q . \
    || die "docker debs not extracted into SSD install-cache"
  ok "SSD install-cache docker debs extracted"
fi
ok "loop SSD UEFI + initrd boot chain"

# initrd content gate — the real boot fails when the deployed initrd is missing
# the userspace libs the systemd initramfs needs (libcrypto.so.3 → modprobe,
# systemd-udevd). File presence alone is NOT enough; unpack and assert contents.
echo "==> verify deployed initrd carries libcrypto/systemd-udevd"
GRUB_INITRD_REL="$(awk '/^[[:space:]]*initrd[[:space:]]+/ {print $2; exit}' "$MNT/boot/grub/grub.cfg")"
[[ -n "$GRUB_INITRD_REL" ]] || die "no grub initrd path to inspect"
DEPLOYED_INITRD="$MNT/${GRUB_INITRD_REL#/}"
[[ -f "$DEPLOYED_INITRD" ]] || die "grub-referenced initrd missing: $GRUB_INITRD_REL"
INITRD_OUT="$WORK/initrd-unpack"
mkdir -p "$INITRD_OUT"
if command -v unmkinitramfs >/dev/null 2>&1; then
  unmkinitramfs "$DEPLOYED_INITRD" "$INITRD_OUT" 2>/dev/null || die "unmkinitramfs failed on deployed initrd"
else
  ( cd "$INITRD_OUT" && \
    ( zstdcat "$DEPLOYED_INITRD" 2>/dev/null || xzcat "$DEPLOYED_INITRD" 2>/dev/null || \
      gzip -dc "$DEPLOYED_INITRD" 2>/dev/null || cat "$DEPLOYED_INITRD" ) | cpio -idmu 2>/dev/null ) || \
    die "initrd cpio extract failed"
fi
find "$INITRD_OUT" -path '*/libcrypto.so.3' 2>/dev/null | grep -q . || \
  die "deployed initrd MISSING libcrypto.so.3 (boot would fail: modprobe/systemd-udevd)"
find "$INITRD_OUT" -name 'systemd-udevd' 2>/dev/null | grep -q . || \
  die "deployed initrd MISSING systemd-udevd"
ok "deployed initrd contains libcrypto.so.3 + systemd-udevd"

echo ""
echo "PASS deploy-bootstrap virtual test"
echo "LOG $LOG"
