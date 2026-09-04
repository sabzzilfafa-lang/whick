#!/usr/bin/env bash
# Local end-to-end install gate: prove a fresh deploy actually BOOTS clean.
#   1) deploy bootstrap rootfs onto a virtual loop SSD (+ initrd content gate)
#   2) QEMU-boot that SSD and assert it reaches userspace with NO libcrypto error
#   3) negative self-test: a libcrypto-stripped initrd MUST fail (harness sanity)
#
# This is the gate to run after any change to deploy_bootstrap_rootfs.sh or the
# bootstrap image build. It replaces the "fix → reflash device → watch" loop with
# a hermetic reproduction that exercises the exact field failure mode.
#
# Usage: test-install-e2e-local.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
UAB="$REPO_ROOT/3_product/uab"
SANDBOX="${WHICK_SANDBOX_SCRATCH:-/data/whick-ai/sandbox-scratch}"
BOOTSTRAP="${WHICK_BOOTSTRAP_ROOTFS:-/mnt/music/whick-cc/build-staging/uab/whick-bootstrap-rootfs.tar.xz}"

if [[ -z "${WHICK_E2E_IN_DOCKER:-}" ]]; then
  echo "==> re-exec end-to-end gate in whick-install-test (privileged + KVM)"
  exec docker run --rm --privileged --device /dev/kvm \
    -v /data:/data -v /mnt/music:/mnt/music \
    -e WHICK_E2E_IN_DOCKER=1 \
    -e WHICK_SANDBOX_SCRATCH="$SANDBOX" \
    -e WHICK_BOOTSTRAP_ROOTFS="$BOOTSTRAP" \
    whick-install-test:latest \
    bash "$UAB/scripts/test-install-e2e-local.sh"
fi

say() { echo; echo "########## $* ##########"; }
die() { echo "E2E FAIL: $*" >&2; exit 1; }

# Shared loop-device prep (containers start without /dev/loopN nodes).
dmsetup remove_all 2>/dev/null || true
losetup -D 2>/dev/null || true
modprobe loop 2>/dev/null || true
for i in $(seq 0 31); do [[ -e /dev/loop$i ]] || mknod -m660 "/dev/loop$i" b 7 "$i" 2>/dev/null || true; done

[[ -f "$BOOTSTRAP" ]] || die "bootstrap rootfs not found: $BOOTSTRAP"

say "STEP 1/3  deploy bootstrap rootfs to virtual SSD"
export WHICK_DEPLOY_VIRTUAL_IN_DOCKER=1
export WHICK_BOOTSTRAP_ROOTFS="$BOOTSTRAP"
bash "$UAB/scripts/test-deploy-bootstrap-virtual-docker.sh" || die "deploy lab test failed"

DISK="$(ls -t "$SANDBOX"/runs/deploy-bootstrap-virtual-*/disk.img 2>/dev/null | head -1 || true)"
[[ -n "$DISK" && -f "$DISK" ]] || die "deploy produced no disk.img"
echo "==> deployed disk: $DISK"

say "STEP 2/3  QEMU boot the deployed SSD (positive)"
export WHICK_QEMU_IN_DOCKER=1
WHICK_QEMU_BREAK_LIB=0 bash "$UAB/scripts/test-ssd-boot-qemu.sh" "$DISK" || die "deployed SSD did not boot clean"

say "STEP 3/3  QEMU negative self-test (libcrypto-stripped initrd MUST fail)"
WHICK_QEMU_BREAK_LIB=1 bash "$UAB/scripts/test-ssd-boot-qemu.sh" "$DISK" || die "negative self-test failed (harness blind?)"

say "E2E PASS — fresh deploy boots to userspace, no libcrypto failure; harness verified sound"
