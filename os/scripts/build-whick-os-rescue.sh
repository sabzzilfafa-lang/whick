#!/usr/bin/env bash
# DEPRECATED · REMOVED (2026-07-26)
# rescue 파티션 이미지 빌드 폐기. 전체 재설치는 USB Live(connect-wired/wireless)만.
set -euo pipefail
echo "ERROR: build-whick-os-rescue.sh removed — rescue partition design discarded." >&2
echo "Use connect-wired / connect-wireless Live ISO for full OS reinstall." >&2
exit 1
