# Alpine connect USB / Alpine rescue — DEPRECATED (2026-07-26)
#
# Whick OS = Ubuntu 26.04 LTS only (Live + SSD + Rescue).
# Do not add features to Alpine ISO / Alpine rescue.
# Keep build scripts until whick-os-live.iso ships and field USB is cut over.
#
# Replacement:
#   Live:  3_product/os/scripts/build-whick-os-live.sh
#   SSD:   3_product/os/scripts/build-whick-os-rootfs.sh
#   Rescue: 3_product/os/scripts/build-whick-os-rescue.sh
# SSOT: docs/WHICK-OS.md

status: deprecated
replaced_by: whick-os
alpine_version_last: "3.21.7"
scripts_frozen:
  - 3_product/uab/scripts/build-connect-usb-package.sh
  - 3_product/uab/scripts/patch-alpine-live-iso.sh
  - 3_product/uab/scripts/build-whick-rescue-image.sh
