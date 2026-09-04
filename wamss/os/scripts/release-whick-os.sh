#!/usr/bin/env bash
# Whick OS 빌드 산출 staging — CC 솔루션 코드는 connect-* / music-01
# Live ISO 등록: register-solution-cc.sh connect-wired|connect-wireless
# rootfs: music-01 components 핀
set -euo pipefail

OS_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPTS="$OS_ROOT/scripts"
OUT="${WHICK_OS_OUT:-$OS_ROOT/../dist/os}"
STAGING="${WHICK_OS_STAGING:-/mnt/music/whick-cc/build-staging/whick-os}"

mkdir -p "$OUT" "$STAGING"

echo "==> Whick OS release checks"
bash "$SCRIPTS/build-whick-os-rootfs.sh" --check
bash "$SCRIPTS/build-whick-os-live.sh" --check
# rescue 빌드 폐기 (2026-07-26) — USB Live 전체 재설치만

echo "==> Live payload (wired)"
WHICK_OS_NET_PROFILE=wired WHICK_OS_LIVE_OUT="$OUT" bash "$SCRIPTS/build-whick-os-live.sh" --payload
echo "==> Live payload (wireless)"
WHICK_OS_NET_PROFILE=wireless WHICK_OS_LIVE_OUT="$OUT" bash "$SCRIPTS/build-whick-os-live.sh" --payload

mkdir -p "$STAGING"
cp -f "$OUT"/whick-os-live-payload-*.tar.zst "$STAGING/" 2>/dev/null || true
cp -f "$OUT"/whick-os-rootfs.tar.xz "$STAGING/" 2>/dev/null || true
# whick-os-rescue.tar.zst — 더 이상 스테이징하지 않음
cp -f /data/whick-ai/2_control_center/config/solutions/connect-wired.json "$STAGING/" 2>/dev/null || true
cp -f /data/whick-ai/2_control_center/config/solutions/connect-wireless.json "$STAGING/" 2>/dev/null || true
cp -f /data/whick-ai_music_server/docs/WHICK-OS.md "$STAGING/WHICK-OS.md" 2>/dev/null || true

echo "OK  staged → $STAGING"
echo "    Live ISO CC 등록은 connect-wired / connect-wireless (whick-os 솔루션 없음)"
