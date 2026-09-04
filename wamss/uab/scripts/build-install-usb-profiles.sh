#!/usr/bin/env bash
# 유선/무선 USB 베이스 zip (드라이버 분리)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${WHICK_CONNECT_DIST:-$ROOT/../dist/connect-usb}"
SCRIPT="$ROOT/scripts/build-connect-usb-package.sh"

build_profile() {
  local profile="$1"
  local zip_name="$2"
  echo "==> profile=$profile → $zip_name"
  WHICK_USB_PROFILE="$profile" WHICK_CONNECT_ZIP_NAME="$zip_name" bash "$SCRIPT"
  cp -f "$OUT/$zip_name" "$OUT/${zip_name%.zip}-base.zip"
  echo "OK  $OUT/${zip_name%.zip}-base.zip"
}

mkdir -p "$OUT/custom"

build_profile wired "USB설치용-유선.zip"
build_profile wireless "USB설치용-무선.zip"

echo ""
echo "OK  wired + wireless base zips in $OUT"
