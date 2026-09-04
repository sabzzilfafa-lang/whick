#!/usr/bin/env bash
# LEGACY WRAPPER — delegates to Whick OS rootfs builder
# Prefer: 3_product/os/scripts/build-whick-os-rootfs.sh
# See docs/WHICK-OS.md
# product-application-map: gated via apply-product-map.py (pipeline_hooks)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PRODUCT="$(cd "$ROOT/.." && pwd)"
OS_BUILD="$PRODUCT/os/scripts/build-whick-os-rootfs.sh"
if [[ ! -x "$OS_BUILD" && -f "$OS_BUILD" ]]; then
  chmod +x "$OS_BUILD"
fi
if [[ -f "$OS_BUILD" ]]; then
  echo "NOTE: build-whick-bootstrap-rootfs.sh → Whick OS rootfs (generic+docker bake)"
  export WHICK_BOOTSTRAP_OUT="${WHICK_BOOTSTRAP_OUT:-$PRODUCT/dist/uab}"
  export WHICK_OS_OUT="${WHICK_OS_OUT:-$WHICK_BOOTSTRAP_OUT}"
  exec bash "$OS_BUILD" "${1:-build}"
fi
echo "ERROR: Whick OS builder missing: $OS_BUILD" >&2
exit 1
