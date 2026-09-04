#!/usr/bin/env bash
# VIP 사전 신청 provision → 맞춤 USB zip (베이스 overlay)
# Usage:
#   PROVISION_ID=1 ./build-custom-install-usb.sh
#   ./build-custom-install-usb.sh --provision-id 1
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPTS="$ROOT/scripts"
OUT="${WHICK_CONNECT_DIST:-/mnt/music/whick-cc/build-staging/connect-usb}"
BASE_ZIP="${WHICK_CONNECT_BASE_ZIP:-$OUT/USB설치용-무선.zip}"
CC_URL="${WHICK_CC_API_URL:-https://admin.whick.org/api/v1}"
CC_SECRET="${WHICK_CC_SITE_SECRET:-${CC_SITE_SECRET:-}}"

PROVISION_ID="${PROVISION_ID:-}"

usage() {
  cat <<EOF
Usage: $(basename "$0") --provision-id ID

  베이스 connect-usb zip + provision.json + bootstrap 세션 주입

Env:
  WHICK_CC_API_URL       CC API base
  WHICK_CC_SITE_SECRET   x-cc-site-secret (필수)
  WHICK_CONNECT_BASE_ZIP 베이스 zip (없으면 USB설치용.zip 사용)
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --provision-id) PROVISION_ID="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown: $1" >&2; usage; exit 1 ;;
  esac
done

[[ -n "$PROVISION_ID" ]] || { echo "ERROR: --provision-id required" >&2; exit 1; }
[[ -n "$CC_SECRET" ]] || { echo "ERROR: WHICK_CC_SITE_SECRET required" >&2; exit 1; }

# Prefer mode-specific env from cc-api-install compose
if [[ -n "${WHICK_CONNECT_WIRELESS_BASE_ZIP:-}" && -f "${WHICK_CONNECT_WIRELESS_BASE_ZIP}" ]]; then
  BASE_ZIP="$WHICK_CONNECT_WIRELESS_BASE_ZIP"
elif [[ -n "${WHICK_CONNECT_BASE_ZIP:-}" && -f "${WHICK_CONNECT_BASE_ZIP}" ]]; then
  BASE_ZIP="$WHICK_CONNECT_BASE_ZIP"
fi

if [[ ! -f "$BASE_ZIP" ]]; then
  if [[ -f "$OUT/USB설치용-무선.zip" ]]; then
    BASE_ZIP="$OUT/USB설치용-무선.zip"
  elif [[ -f "$OUT/USB설치용-base.zip" ]]; then
    BASE_ZIP="$OUT/USB설치용-base.zip"
  elif [[ -f "$OUT/USB설치용.zip" ]]; then
    BASE_ZIP="$OUT/USB설치용.zip"
  else
    echo "==> base zip missing — building wireless package first"
    WHICK_USB_PROFILE=wireless WHICK_CONNECT_ZIP_NAME="USB설치용-무선.zip" \
      WHICK_CONNECT_DIST="$OUT" "$SCRIPTS/build-connect-usb-package.sh"
    BASE_ZIP="$OUT/USB설치용-무선.zip"
  fi
fi

ART_JSON="$(mktemp)"
trap 'rm -f "$ART_JSON"; rm -rf "${ZIP_OUT:-}"' EXIT

ART_URL="${CC_URL%/}/install/provisions/${PROVISION_ID}/artifact"
if command -v curl >/dev/null 2>&1; then
  HTTP="$(curl -fsSL -w '%{http_code}' -o "$ART_JSON" \
    -H "x-cc-site-secret: $CC_SECRET" \
    "$ART_URL" || true)"
elif command -v wget >/dev/null 2>&1; then
  if wget -q -O "$ART_JSON" --header="x-cc-site-secret: $CC_SECRET" "$ART_URL"; then
    HTTP=200
  else
    HTTP="000"
  fi
else
  echo "ERROR: curl/wget not found (cannot fetch provision artifact)" >&2
  exit 1
fi
if [[ "$HTTP" != "200" ]]; then
  echo "ERROR: artifact HTTP $HTTP" >&2
  cat "$ART_JSON" >&2 || true
  exit 1
fi

if command -v python3 >/dev/null 2>&1; then
  DEVICE_CODE="$(python3 -c "import json; d=json.load(open('$ART_JSON')); a=(d.get('data') or {}).get('artifact') or d.get('artifact') or d; print(a['device_code'])")"
else
  DEVICE_CODE="$(node -e "const d=JSON.parse(require('fs').readFileSync(process.argv[1],'utf8')); const a=(d.data&&d.data.artifact)||d.artifact||d; console.log(a.device_code)" "$ART_JSON")"
fi
# 같은 파일명 브라우저 캐시로 옛 ISO가 구워지는 사고 방지 — 분 단위 스탬프
ZIP_STAMP="$(TZ=Asia/Seoul date +%m%d%H%M)"
ZIP_NAME="USB설치-${DEVICE_CODE}-${ZIP_STAMP}.zip"
# /tmp(tmpfs) 에 2.7G ISO 풀면 short read·용량 경합 → SSD staging 사용
mkdir -p "$OUT/custom"
ZIP_OUT="$(mktemp -d "$OUT/custom/.shell-build-XXXXXX")"
trap 'rm -f "$ART_JSON"; rm -rf "$ZIP_OUT"' EXIT
WORK="$ZIP_OUT/pkg"
mkdir -p "$WORK/whick-boot-connect"

ISO_NAME="whick-os-live-wireless.iso"
ISO_SRC=""
for cand in \
  "$(dirname "$BASE_ZIP")/$ISO_NAME" \
  "/data/whick-ai_music_server/3_product/dist/os/$ISO_NAME" \
  "/mnt/ssd2/whick-cc/whick-dist-test/os/$ISO_NAME"
do
  if [[ -f "$cand" ]]; then ISO_SRC="$cand"; break; fi
done
if [[ -n "$ISO_SRC" ]]; then
  cp -f "$ISO_SRC" "$WORK/$ISO_NAME"
else
  echo "ERROR: live ISO missing next to base zip (refusing ZIP64 full unzip)" >&2
  exit 1
fi
if [[ -f "$ROOT/windows/Whick-USB-Maker.ps1" ]]; then
  cp -f "$ROOT/windows/Whick-USB-Maker.ps1" "$WORK/Whick-USB-Maker.ps1"
fi
if [[ -f "$ROOT/windows/make-usb.bat" ]]; then
  cp -f "$ROOT/windows/make-usb.bat" "$WORK/make-usb.bat"
fi
if [[ -f "$ROOT/windows/Whick-USB-Maker.exe" ]]; then
  cp -f "$ROOT/windows/Whick-USB-Maker.exe" "$WORK/Whick-USB-Maker.exe"
fi
cat >"$WORK/START-HERE.txt" <<EOF
Whick 뮤직서버 무선 설치 USB 만들기
========================================

1. USB (8GB 이상)를 PC에 꽂습니다.
2. make-usb.bat 을 실행합니다. (관리자 권한 허용)
3. 목록에서 USB를 고르고, 삭제 경고에 동의한 뒤 [시작]을 누릅니다.
4. 완료되면 USB를 미니PC에 꽂고, BIOS에서 USB로 부팅합니다.

※ Rufus / Etcher / 추가 프로그램 설치 불필요
※ 같은 폴더의 ${ISO_NAME} 이 자동으로 기록됩니다.
※ USB의 기존 데이터는 모두 삭제됩니다.
EOF

if command -v python3 >/dev/null 2>&1; then
python3 - "$ART_JSON" "$WORK/whick-boot-connect" <<'PY'
import json, os, sys
from pathlib import Path

art_path, dest = sys.argv[1], Path(sys.argv[2])
raw = json.load(open(art_path))
artifact = raw.get("data", {}).get("artifact") or raw.get("artifact") or raw

access_mode = artifact.get("access_mode") or "wireless"
net_profile = "wired" if access_mode == "wired" else "wireless"
(dest / "net-profile").write_text(net_profile + "\n", encoding="utf-8")

provision = {
    "version": artifact.get("version", 1),
    "provision_id": artifact["provision_id"],
    "session_id": artifact["session_id"],
    "device_code": artifact["device_code"],
    "access_mode": artifact["access_mode"],
    "mb_id": artifact.get("mb_id", ""),
    "wifi_ssid": artifact.get("wifi_ssid", ""),
    "wifi_password": artifact.get("wifi_password", ""),
}
bootstrap = {
    "session_id": artifact["session_id"],
    "device_code": artifact["device_code"],
    "bootstrap_token": artifact["bootstrap_token"],
}

prov_path = dest / "provision.json"
boot_path = dest / "whick-bootstrap-session.json"
prov_path.write_text(json.dumps(provision, ensure_ascii=False, indent=2), encoding="utf-8")
boot_path.write_text(json.dumps(bootstrap, ensure_ascii=False, indent=2), encoding="utf-8")
os.chmod(prov_path, 0o600)
os.chmod(boot_path, 0o600)
print(f"  provision → {prov_path.name} ({provision['access_mode']})")
PY
else
ART_JSON="$ART_JSON" DEST="$WORK/whick-boot-connect" node <<'NODE'
const fs = require('fs');
const path = require('path');
const artPath = process.env.ART_JSON;
const dest = process.env.DEST;
const raw = JSON.parse(fs.readFileSync(artPath, 'utf8'));
const artifact = (raw.data && raw.data.artifact) || raw.artifact || raw;
const access_mode = artifact.access_mode || 'wireless';
const net_profile = access_mode === 'wired' ? 'wired' : 'wireless';
fs.writeFileSync(path.join(dest, 'net-profile'), net_profile + '\n');
const provision = {
  version: artifact.version || 1,
  provision_id: artifact.provision_id,
  session_id: artifact.session_id,
  device_code: artifact.device_code,
  access_mode: artifact.access_mode,
  mb_id: artifact.mb_id || '',
  wifi_ssid: artifact.wifi_ssid || '',
  wifi_password: artifact.wifi_password || '',
};
const bootstrap = {
  session_id: artifact.session_id,
  device_code: artifact.device_code,
  bootstrap_token: artifact.bootstrap_token,
};
const provPath = path.join(dest, 'provision.json');
const bootPath = path.join(dest, 'whick-bootstrap-session.json');
fs.writeFileSync(provPath, JSON.stringify(provision, null, 2));
fs.writeFileSync(bootPath, JSON.stringify(bootstrap, null, 2));
fs.chmodSync(provPath, 0o600);
fs.chmodSync(bootPath, 0o600);
console.log(`  provision → provision.json (${provision.access_mode})`);
NODE
fi

# ISO-DD 만 하는 USB Maker 대비 — provision 을 Live ISO 트리에 주입·remaster
INJECT_SCRIPT="$SCRIPTS/inject-provision-into-live-iso.sh"
INJECT_DOCKER="$SCRIPTS/run-inject-provision-iso.sh"
SETUP_PY="$ROOT/boot-connect/whick-customer-setup.py"
ISO_FILE="$(find "$WORK" -maxdepth 1 -type f \( -name 'whick-os-live-wireless.iso' -o -name 'whick-os-live-wired.iso' -o -name 'whick-os-live-*.iso' \) | head -1 || true)"
RUN_INJECT=""
if [[ -n "$ISO_FILE" && -f "$INJECT_DOCKER" ]]; then
  RUN_INJECT="$INJECT_DOCKER"
elif [[ -n "$ISO_FILE" && -f "$INJECT_SCRIPT" ]]; then
  RUN_INJECT="$INJECT_SCRIPT"
fi
if [[ -n "$ISO_FILE" && -n "$RUN_INJECT" ]]; then
  echo "==> inject provision into $(basename "$ISO_FILE") via $(basename "$RUN_INJECT")"
  inj_args=(--iso "$ISO_FILE" --boot-dir "$WORK/whick-boot-connect" --out "$ISO_FILE")
  [[ -f "$SETUP_PY" ]] && inj_args+=(--setup-py "$SETUP_PY")
  bash "$RUN_INJECT" "${inj_args[@]}"
  # 무선: live-debug.env SSID 핀 검증
  if [[ -f "$WORK/whick-boot-connect/net-profile" ]] && grep -qx wireless "$WORK/whick-boot-connect/net-profile"; then
    if command -v python3 >/dev/null 2>&1; then
      SSID_EXPECT="$(python3 -c "import json;print(json.load(open('$WORK/whick-boot-connect/provision.json')).get('wifi_ssid') or '')")"
    else
      SSID_EXPECT="$(node -e "console.log(JSON.parse(require('fs').readFileSync(process.argv[1],'utf8')).wifi_ssid||'')" "$WORK/whick-boot-connect/provision.json")"
    fi
    [[ -n "$SSID_EXPECT" ]] || { echo "ERROR: empty wifi_ssid" >&2; exit 1; }
    VERIFY_DIR="$(mktemp -d)"
    trap 'rm -rf "$VERIFY_DIR"; rm -f "$ART_JSON"; rm -rf "$ZIP_OUT"' EXIT
    export DOCKER_HOST="${DOCKER_HOST:-unix:///var/run/docker.sock}"
    docker run --rm -v "$ISO_FILE:/in.iso:ro" -v "$VERIFY_DIR:/out" --entrypoint xorriso whick/xorriso:local \
      -osirrox on -indev /in.iso -extract /whick-os/etc/whick/live-debug.env /out/live-debug.env
    grep -F "WHICK_PROVISION_WIFI_SSID=" "$VERIFY_DIR/live-debug.env" | grep -Fq "$SSID_EXPECT" \
      || { echo "ERROR: ISO missing WHICK_PROVISION_WIFI_SSID=$SSID_EXPECT" >&2; exit 1; }
    echo "OK  ISO Wi-Fi pin verified ($SSID_EXPECT)"
  fi
elif [[ -n "$ISO_FILE" ]]; then
  echo "ERROR: inject script missing: $INJECT_DOCKER / $INJECT_SCRIPT" >&2
  exit 1
fi

# 리모컨 외부·LTE named tunnel 번들 주입 (provision-music-tunnel.sh 산출물)
# WHICK_TUNNEL_BUNDLE_DIR 지정 시 whick-boot-connect/tunnel/ 로 동봉 → 설치 시 자동 활성.
if [[ -n "${WHICK_TUNNEL_BUNDLE_DIR:-}" && -f "${WHICK_TUNNEL_BUNDLE_DIR}/config.yml" ]]; then
  mkdir -p "$WORK/whick-boot-connect/tunnel"
  cp -f "${WHICK_TUNNEL_BUNDLE_DIR}"/*.yml "${WHICK_TUNNEL_BUNDLE_DIR}"/*.json "$WORK/whick-boot-connect/tunnel/" 2>/dev/null || true
  [[ -f "${WHICK_TUNNEL_BUNDLE_DIR}/device-token" ]] && cp -f "${WHICK_TUNNEL_BUNDLE_DIR}/device-token" "$WORK/whick-boot-connect/tunnel/"
  chmod 600 "$WORK/whick-boot-connect/tunnel/"*.json 2>/dev/null || true
  echo "  tunnel → whick-boot-connect/tunnel ($(basename "${WHICK_TUNNEL_BUNDLE_DIR}"))"
fi

mkdir -p "$OUT/custom"
# Info-ZIP zip CLI historically broke Korean filenames; prefer ASCII make-usb.bat on Windows — use Python ZIP_STORED + UTF-8
python3 - "$WORK" "$OUT/custom/$ZIP_NAME" <<'PY'
import sys, zipfile
from pathlib import Path
src, out = Path(sys.argv[1]), Path(sys.argv[2])
out.parent.mkdir(parents=True, exist_ok=True)
if out.exists():
    out.unlink()
with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_STORED) as zf:
    for p in sorted(src.rglob("*")):
        if p.is_file():
            zf.write(p, p.relative_to(src).as_posix())
            print("  +", p.relative_to(src).as_posix(), p.stat().st_size)
print("wrote", out)
PY

MARK_URL="${CC_URL%/}/install/provisions/${PROVISION_ID}/mark-built"
if command -v curl >/dev/null 2>&1; then
  curl -fsSL -X POST -H "x-cc-site-secret: $CC_SECRET" "$MARK_URL" >/dev/null
elif command -v wget >/dev/null 2>&1; then
  wget -q -O /dev/null --method=POST --header="x-cc-site-secret: $CC_SECRET" "$MARK_URL" || true
else
  CC_SECRET="$CC_SECRET" MARK_URL="$MARK_URL" node <<'NODE'
const https = require('http');
const u = new URL(process.env.MARK_URL);
const req = https.request({
  hostname: u.hostname,
  port: u.port || 80,
  path: u.pathname + u.search,
  method: 'POST',
  headers: { 'x-cc-site-secret': process.env.CC_SECRET },
}, (res) => { res.resume(); });
req.on('error', () => {});
req.end();
NODE
fi

echo "OK  $OUT/custom/$ZIP_NAME"
echo "    provision_id=$PROVISION_ID device=$DEVICE_CODE"
