#!/usr/bin/env bash
# 본사 서버 — 노트북 USB용 번들 생성
#   ./scripts/build-laptop-usb.sh
#   ./scripts/build-laptop-usb.sh /media/whick/USBNAME   # USB 마운트 경로에 직접 복사
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STAMP="$(date +%Y%m%d)"
OUT="${WHICK_USB_OUT:-$ROOT/dist/laptop-usb}"
BUNDLE="${OUT}/whick-laptop-usb"
USB_DEST="${1:-}"

echo "==> Whick 노트북 USB 번들"
echo "    소스: $ROOT"
echo "    출력: $BUNDLE"
echo ""

mkdir -p "$BUNDLE"

echo "==> whick-3_product 복사"
rsync -a --delete \
  --exclude '.env' \
  --exclude 'library/incoming/*' \
  --exclude 'dist/' \
  --exclude '.git/' \
  "$ROOT/" "$BUNDLE/whick-3_product/"

echo "==> USB 루트 스크립트"
cp -f "$ROOT/usb-bundle/START-HERE.md" "$BUNDLE/"
cp -f "$ROOT/usb-bundle/"*.sh "$BUNDLE/"
chmod +x "$BUNDLE"/*.sh
"$BUNDLE/make-desktop-launchers.sh"

# Windows에서도 읽을 수 있게 짧은 txt
cat > "$BUNDLE/START-HERE.txt" <<'EOF'
Whick 노트북 USB — Ubuntu 24.04/26.04 · Wi-Fi 연결 후

★ 처음 1회 (부팅 자동):
  Whick-USB-부팅자동.desktop 더블클릭 → 등록
  → USB 꽂고 재부팅·로그인 → 자동 설치

★ 지금 바로:
  Whick-USB-설치.desktop 더블클릭

터미널: ./auto-install.sh
자세한 설명: START-HERE.md
EOF

SIZE="$(du -sh "$BUNDLE" | cut -f1)"
echo ""
echo "==> 완료: $BUNDLE ($SIZE)"
echo ""
echo "USB/iODD에 복사:"
echo "  cp -a $BUNDLE/* /media/USER/USBNAME/whick-laptop-usb/"
echo "  또는: $0 /media/USER/USBNAME"
echo ""

if [[ -n "$USB_DEST" ]]; then
  if [[ ! -d "$USB_DEST" ]]; then
    echo "ERROR: USB 경로 없음: $USB_DEST" >&2
    exit 1
  fi
  DEST="${USB_DEST%/}/whick-laptop-usb"
  echo "==> USB 직접 복사 → $DEST"
  mkdir -p "$DEST"
  rsync -a --delete "$BUNDLE/" "$DEST/"
  echo "OK  $DEST"
fi
