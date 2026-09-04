#!/usr/bin/env bash
# Boot a deployed SSD image under QEMU/KVM and assert it reaches userspace
# WITHOUT the "libcrypto.so.3: cannot open shared object file" failure that
# bricked the field installs. We boot the kernel+initrd directly (-kernel/-initrd)
# to bypass the signed-shim/GRUB serial-console quirks and exercise exactly the
# path that fails in the field: initramfs -> root pivot -> systemd-udevd/modprobe.
#
# Usage:
#   test-ssd-boot-qemu.sh [/path/to/disk.img]
# If no image is given, the newest deploy-bootstrap-virtual run image is used.
#
# Runs inside a privileged container with /dev/kvm. When invoked on a host that
# lacks qemu, it re-execs itself in the whick-install-test image.
set -euo pipefail

SANDBOX="${WHICK_SANDBOX_SCRATCH:-/data/whick-ai/sandbox-scratch}"
IMG="${1:-}"
BOOT_TIMEOUT="${WHICK_QEMU_BOOT_TIMEOUT:-110}"

if [[ -z "${WHICK_QEMU_IN_DOCKER:-}" ]]; then
  if ! command -v qemu-system-x86_64 >/dev/null 2>&1; then
    echo "==> re-exec in whick-install-test (no host qemu)"
    exec docker run --rm --privileged --device /dev/kvm \
      -v /data:/data \
      -e WHICK_QEMU_IN_DOCKER=1 \
      -e WHICK_SANDBOX_SCRATCH="$SANDBOX" \
      -e WHICK_QEMU_BOOT_TIMEOUT="$BOOT_TIMEOUT" \
      -e WHICK_QEMU_BREAK_LIB="${WHICK_QEMU_BREAK_LIB:-0}" \
      whick-install-test:latest \
      bash "$(cd "$(dirname "$0")" && pwd)/$(basename "$0")" "$IMG"
  fi
fi

die() { echo "FAIL: $*" >&2; exit 1; }
ok() { echo "OK $*"; }

if [[ -z "$IMG" ]]; then
  IMG="$(ls -t "$SANDBOX"/runs/deploy-bootstrap-virtual-*/disk.img 2>/dev/null | head -1 || true)"
fi
[[ -n "$IMG" && -f "$IMG" ]] || die "no disk image (pass one or run deploy test first): $IMG"
echo "==> boot image: $IMG"

WORK="$SANDBOX/runs/ssd-boot-qemu-$$"
mkdir -p "$WORK"
SERIAL="$WORK/serial.log"
cleanup() {
  set +e
  umount "$WORK/mnt" 2>/dev/null || true
  if [[ -n "${LO:-}" ]]; then
    kpartx -d "$LO" 2>/dev/null || true
    losetup -d "$LO" 2>/dev/null || true
  fi
}
trap cleanup EXIT

# Fresh loop devices (containers often start without /dev/loopN nodes).
dmsetup remove_all 2>/dev/null || true
losetup -D 2>/dev/null || true
modprobe loop 2>/dev/null || true
for i in $(seq 0 31); do [[ -e /dev/loop$i ]] || mknod -m660 "/dev/loop$i" b 7 "$i" 2>/dev/null || true; done

LO="$(losetup -fP --show "$IMG")"
partprobe "$LO" 2>/dev/null || true
sleep 1
# Partition nodes can be flaky right after a deploy run; fall back to kpartx
# device-mapper nodes, then to label lookup.
if [[ ! -b "${LO}p2" && ! -b "/dev/mapper/$(basename "$LO")p2" ]]; then
  kpartx -av "$LO" >/dev/null 2>&1 || true
  sleep 1
fi
ROOT_DEV=""
for cand in "${LO}p2" "/dev/mapper/$(basename "$LO")p2"; do
  [[ -b "$cand" ]] && { ROOT_DEV="$cand"; break; }
done
[[ -z "$ROOT_DEV" ]] && ROOT_DEV="$(blkid -L whick-root 2>/dev/null || true)"
[[ -b "$ROOT_DEV" ]] || die "root partition not found (tried ${LO}p2, mapper, label whick-root)"
RUUID="$(blkid -s UUID -o value "$ROOT_DEV" || true)"
[[ -n "$RUUID" ]] || die "cannot read root UUID from $ROOT_DEV"
ok "root partition $ROOT_DEV UUID=$RUUID"

mkdir -p "$WORK/mnt"
mount "$ROOT_DEV" "$WORK/mnt"
KIMG="$(ls "$WORK"/mnt/boot/vmlinuz-* 2>/dev/null | head -1 || true)"
IIMG="$(ls "$WORK"/mnt/boot/initrd.img-* 2>/dev/null | head -1 || true)"
[[ -f "$KIMG" && -f "$IIMG" ]] || die "kernel/initrd missing on root /boot"
cp "$KIMG" "$WORK/vmlinuz"
cp "$IIMG" "$WORK/initrd"
ok "extracted kernel ($(stat -c%s "$WORK/vmlinuz") B) + initrd ($(stat -c%s "$WORK/initrd") B)"
umount "$WORK/mnt"
kpartx -d "$LO" 2>/dev/null || true
losetup -d "$LO"; LO=""

# Negative self-test: deliberately strip libcrypto.so.3 from the initrd to prove
# this harness actually surfaces the field failure (guards against a blind test).
if [[ "${WHICK_QEMU_BREAK_LIB:-0}" == "1" ]]; then
  echo "==> NEGATIVE mode: removing libcrypto.so.3 from initrd"
  rm -rf "$WORK/un"; mkdir -p "$WORK/un"
  unmkinitramfs "$WORK/initrd" "$WORK/un"
  BREAK_BASE="$WORK/un"; [[ -d "$WORK/un/main" ]] && BREAK_BASE="$WORK/un/main"
  rm -f "$BREAK_BASE"/usr/lib/x86_64-linux-gnu/libcrypto.so.3
  ( cd "$BREAK_BASE" && find . -print0 | cpio --null -o -H newc 2>/dev/null | zstd -q -1 ) > "$WORK/initrd.broken"
  mv "$WORK/initrd.broken" "$WORK/initrd"
  ok "repacked broken initrd ($(stat -c%s "$WORK/initrd") B)"
fi

# qcow2 overlay so the boot can write without mutating the deploy artifact.
qemu-img create -f qcow2 -F raw -b "$IMG" "$WORK/ov.qcow2" 24G >/dev/null

echo "==> QEMU direct kernel boot (timeout ${BOOT_TIMEOUT}s)"
set +e
timeout "$BOOT_TIMEOUT" qemu-system-x86_64 -enable-kvm -m 2048 -smp 2 -machine q35 \
  -kernel "$WORK/vmlinuz" -initrd "$WORK/initrd" \
  -append "root=UUID=$RUUID ro console=ttyS0,115200 systemd.unit=multi-user.target net.ifnames=0" \
  -drive file="$WORK/ov.qcow2",format=qcow2,if=virtio \
  -nographic -serial mon:stdio -display none >"$SERIAL" 2>&1
set -e

# Strip ANSI for gr:ep-ability.
CLEAN="$WORK/serial.clean.log"
sed -E 's/\x1b\[[0-9;?]*[a-zA-Z]//g' "$SERIAL" > "$CLEAN" || cp "$SERIAL" "$CLEAN"

echo "=== serial tail (cleaned) ==="
tail -40 "$CLEAN"
echo "=== verdict ==="

grep -q "Linux version" "$CLEAN" || die "kernel never started (no 'Linux version' on serial) — see $CLEAN"
ok "kernel started"

if [[ "${WHICK_QEMU_BREAK_LIB:-0}" == "1" ]]; then
  if grep -qiE "libcrypto\.so\.3|cannot open shared object" "$CLEAN"; then
    grep -iE "libcrypto|cannot open shared" "$CLEAN" | head -5
    ok "NEGATIVE: harness reproduced the libcrypto boot failure (harness is sound)"
    echo "PASS ssd-boot-qemu (negative)"
    exit 0
  fi
  die "NEGATIVE: broken initrd did NOT surface a libcrypto error — harness is blind"
fi

if grep -qi "libcrypto.so.3" "$CLEAN" || grep -qi "cannot open shared object file" "$CLEAN"; then
  echo "---- offending lines ----"
  grep -iE "libcrypto|cannot open shared" "$CLEAN" | head
  die "libcrypto.so.3 boot failure reproduced — initrd is NOT boot-ready"
fi
ok "no libcrypto.so.3 / shared-object errors"

if grep -q "Kernel panic" "$CLEAN"; then
  grep -A3 "Kernel panic" "$CLEAN" | head
  die "kernel panic during boot"
fi

# Success = we reached real userspace (systemd target or a getty login prompt).
if grep -qE "Reached target .*(Multi-User|multi-user|Login|Basic System)" "$CLEAN" \
   || grep -qE "login:" "$CLEAN" \
   || grep -qiE "Welcome to (Ubuntu|Whick)" "$CLEAN"; then
  ok "reached userspace (systemd multi-user / login)"
  echo "PASS ssd-boot-qemu"
  exit 0
fi

echo "---- could not confirm userspace; relevant markers ----"
grep -aiE "systemd|Reached target|Started|udevd|Failed" "$CLEAN" | tail -20
die "boot did not clearly reach userspace within ${BOOT_TIMEOUT}s (no libcrypto error though)"
