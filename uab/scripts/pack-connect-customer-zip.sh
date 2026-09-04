#!/usr/bin/env bash
# Whick OS Live ISO + Windows USB Maker → 고객용 단일 zip
# 다운로드 1회 · 압축 풀기 · make-usb.bat 만 실행
#
# Usage:
#   WHICK_USB_PROFILE=wired  ./pack-connect-customer-zip.sh
#   WHICK_USB_PROFILE=wireless ./pack-connect-customer-zip.sh
#   ./pack-connect-customer-zip.sh /path/to/whick-os-live-wired.iso
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WIN="$ROOT/windows"
PRODUCT_DIST="${WHICK_OS_LIVE_OUT:-$ROOT/../dist/os}"
DIST_DIR="${WHICK_CONNECT_CUSTOMER_DIST:-/mnt/music/whick-cc/whick-dist/os}"

PROFILE="${WHICK_USB_PROFILE:-wired}"
case "$PROFILE" in
  wired)
    ISO_NAME="whick-os-live-wired.iso"
    ZIP_NAME="${WHICK_CONNECT_ZIP_NAME:-USB설치용-유선.zip}"
    LABEL="유선"
    ;;
  wireless)
    ISO_NAME="whick-os-live-wireless.iso"
    ZIP_NAME="${WHICK_CONNECT_ZIP_NAME:-USB설치용-무선.zip}"
    LABEL="무선"
    ;;
  *)
    echo "WHICK_USB_PROFILE must be wired or wireless" >&2
    exit 1
    ;;
esac

ISO_SRC="${1:-}"
if [[ -z "$ISO_SRC" ]]; then
  for cand in \
    "$PRODUCT_DIST/$ISO_NAME" \
    "$DIST_DIR/$ISO_NAME" \
    "/data/whick-ai_music_server/3_product/dist/os/$ISO_NAME"; do
    if [[ -f "$cand" ]]; then
      ISO_SRC="$cand"
      break
    fi
  done
fi
[[ -n "$ISO_SRC" && -f "$ISO_SRC" ]] || {
  echo "ERROR: ISO 없음 ($ISO_NAME)" >&2
  exit 1
}
[[ -f "$WIN/Whick-USB-Maker.ps1" ]] || {
  echo "ERROR: Whick-USB-Maker.ps1 없음" >&2
  exit 1
}
[[ -f "$WIN/Whick-USB-Maker-Launcher.ps1" ]] || {
  echo "ERROR: Whick-USB-Maker-Launcher.ps1 없음 (HTML GUI 런처)" >&2
  exit 1
}
[[ -f "$WIN/app.html" ]] || {
  echo "ERROR: app.html 없음 (HTML GUI)" >&2
  exit 1
}
[[ -f "$WIN/build/build-usb-maker-exe.ps1" ]] || {
  echo "ERROR: build/build-usb-maker-exe.ps1 없음 (EXE 빌드 도구)" >&2
  exit 1
}
[[ -f "$WIN/make-usb.bat" ]] || {
  echo "ERROR: make-usb.bat 없음" >&2
  exit 1
}

mkdir -p "$DIST_DIR"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

echo "==> pack $LABEL customer zip"
echo "    iso: $ISO_SRC"
echo "    out: $DIST_DIR/$ZIP_NAME"

# flat layout — 압축 풀면 바로 bat/ps1/iso 가 보임
cp -f "$ISO_SRC" "$STAGE/$ISO_NAME"
cp -f "$WIN/Whick-USB-Maker.ps1" "$STAGE/Whick-USB-Maker.ps1"
cp -f "$WIN/Whick-USB-Maker-Launcher.ps1" "$STAGE/Whick-USB-Maker-Launcher.ps1"
cp -f "$WIN/app.html" "$STAGE/app.html"
mkdir -p "$STAGE/build"
cp -f "$WIN/build/build-usb-maker-exe.ps1" "$STAGE/build/"
cp -f "$WIN/build/build-usb-maker.bat" "$STAGE/build/"
cp -f "$WIN/make-usb.bat" "$STAGE/make-usb.bat"
if [[ -f "$WIN/Whick-USB-Maker.exe" ]]; then
  cp -f "$WIN/Whick-USB-Maker.exe" "$STAGE/Whick-USB-Maker.exe"
fi

cat >"$STAGE/START-HERE.txt" <<EOF
Whick 뮤직서버 ${LABEL} 설치 USB 만들기
========================================

1. Plug in a USB stick (8GB+) / USB (8GB 이상)를 꽂습니다
2. Double-click "Whick-USB-Maker" / Whick-USB-Maker 더블클릭 (allow the Windows prompt / Windows 확인창에서 '예')
3. Select your USB from the list and click Start / USB 선택 후 시작
4. Boot the mini PC from the USB / 완료 후 미니PC를 USB로 부팅

* EXE file not included? Build it yourself (one time, internet needed):
  - Open the "build" folder and double-click "build-usb-maker.bat"
  - When done: move build\Whick-USB-Maker.exe to this folder
* EXE 파일이 없나요? 직접 만들 수 있습니다 (1회, 인터넷 필요):
  - build 폴더의 build-usb-maker.bat 더블클릭
  - 완료 후 build\Whick-USB-Maker.exe를 이 폴더로 이동
* No Rufus/Etcher needed / 추가 프로그램 불필요
* The install image ${ISO_NAME} is written automatically / 같은 폴더의 ISO가 자동 기록
* ALL existing data on the USB will be erased / USB의 기존 데이터는 모두 삭제됩니다
EOF

# ISO는 이미 압축됨 → ZIP_STORED 로 빠른 패킹 (호스트에 zip CLI 없을 수 있음)
rm -f "$DIST_DIR/$ZIP_NAME"
python3 - "$STAGE" "$DIST_DIR/$ZIP_NAME" <<'PY'
import sys, zipfile
from pathlib import Path
stage, out = Path(sys.argv[1]), Path(sys.argv[2])
with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_STORED) as zf:
    for p in sorted(stage.rglob("*")):
        if p.is_file():
            zf.write(p, p.relative_to(stage))
            print("  +", p.relative_to(stage), p.stat().st_size)
print("wrote", out)
PY

# ISO도 dist에 유지 (디버그·직접 DD용) — 이미 같은 파일이면 skip
if [[ "$(readlink -f "$ISO_SRC")" != "$(readlink -f "$DIST_DIR/$ISO_NAME" 2>/dev/null || true)" ]]; then
  cp -f "$ISO_SRC" "$DIST_DIR/$ISO_NAME"
fi

SIZE="$(stat -c%s "$DIST_DIR/$ZIP_NAME")"
SHA="$(sha256sum "$DIST_DIR/$ZIP_NAME" | awk '{print $1}')"
echo "OK  $DIST_DIR/$ZIP_NAME"
echo "    size_bytes=$SIZE"
echo "    sha256=$SHA"
echo "$DIST_DIR/$ZIP_NAME"
