#!/usr/bin/env bash
# 실제 Ubuntu SSD 설치 USB 준비 — bootstrap rootfs 빌드 → prod USB zip
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPTS="$ROOT/scripts"
BOOTSTRAP_OUT="${WHICK_BOOTSTRAP_OUT:-$ROOT/../dist/uab}"
BOOTSTRAP="$BOOTSTRAP_OUT/whick-bootstrap-rootfs.tar.xz"

SKIP_BOOTSTRAP=0
SKIP_USB=0
USB_ARGS=()

usage() {
  cat <<EOF
Usage: $(basename "$0") [options]

  1) build Ubuntu 26.04 (resolute) bootstrap rootfs (debootstrap)
  2) WHICK_PROD_INSTALL=1 USB zip (wired default)

Options:
  --skip-bootstrap   bootstrap 이미 있을 때 생략
  --skip-usb         bootstrap만 빌드
  --no-bump          release-connect-usb --no-bump
  --skip-publish     release-connect-usb --skip-publish
  -h, --help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-bootstrap) SKIP_BOOTSTRAP=1; shift ;;
    --skip-usb) SKIP_USB=1; shift ;;
    --no-bump) USB_ARGS+=(--no-bump); shift ;;
    --skip-publish) USB_ARGS+=(--skip-publish); shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown: $1" >&2; usage; exit 1 ;;
  esac
done

echo "========================================"
echo " Whick prod install prep"
echo " $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo "========================================"

if [[ "$SKIP_BOOTSTRAP" -eq 0 ]]; then
  echo ">>> [1/2] bootstrap rootfs"
  chmod +x "$SCRIPTS/build-whick-bootstrap-rootfs.sh"
  "$SCRIPTS/build-whick-bootstrap-rootfs.sh"
else
  echo ">>> [1/2] bootstrap skipped"
  [[ -f "$BOOTSTRAP" ]] || { echo "missing: $BOOTSTRAP" >&2; exit 1; }
fi

ls -lh "$BOOTSTRAP"
sha256sum "$BOOTSTRAP" | awk '{print "sha256:", $1}'

if [[ "$SKIP_USB" -eq 1 ]]; then
  echo "OK  bootstrap only → $BOOTSTRAP"
  exit 0
fi

echo ">>> [2/2] prod USB (WHICK_PROD_INSTALL=1)"
export WHICK_PROD_INSTALL=1
export WHICK_BOOTSTRAP_ROOTFS="$BOOTSTRAP"
export WHICK_USB_PROFILE="${WHICK_USB_PROFILE:-wired}"
chmod +x "$SCRIPTS/release-connect-usb.sh"
"$SCRIPTS/release-connect-usb.sh" "${USB_ARGS[@]}"

ZIP_DIR="$ROOT/../dist/connect-usb"
ZIP_NAME="${WHICK_CONNECT_ZIP_NAME:-USB설치용-유선.zip}"
echo ""
echo "========================================"
echo " Prod USB ready"
echo "  bootstrap: $BOOTSTRAP"
echo "  zip:       $ZIP_DIR/$ZIP_NAME"
echo ""
echo " MiniPC 테스트:"
echo "  1) zip → make-usb.bat (Windows) 또는 Ventoy USB"
echo "  2) CC orchestrator install_linux → SSD Ubuntu + GRUB"
echo "  3) USB 제거 → SSD 부팅 → first-boot docker/runtime"
echo "========================================"
