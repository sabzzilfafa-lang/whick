#!/usr/bin/env bash
# USB 부팅 연결 테스트 패키지 (Windows 원클릭 Maker + Alpine apkovl)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BC="$ROOT/boot-connect"
PRODUCT_ROOT="$(cd "$ROOT/.." && pwd)"
python3 "$PRODUCT_ROOT/scripts/apply-product-map.py" apply --scope all

resolve_bootstrap_src() {
  if [[ -n "${WHICK_BOOTSTRAP_ROOTFS:-}" && -f "${WHICK_BOOTSTRAP_ROOTFS}" ]]; then
    echo "${WHICK_BOOTSTRAP_ROOTFS}"
    return 0
  fi
  local _bs
  for _bs in \
    "$ROOT/../dist/uab/whick-bootstrap-rootfs.tar.xz" \
    "/mnt/music/whick-cc/build-staging/uab/whick-bootstrap-rootfs.tar.xz" \
    "/data/whick-ai/sandbox-scratch/bootstrap-build-out/whick-bootstrap-rootfs.tar.xz"; do
    if [[ -f "$_bs" ]]; then
      echo "$_bs"
      return 0
    fi
  done
  echo "$ROOT/../dist/uab/whick-bootstrap-rootfs.tar.xz"
}

lock_json_path() {
  for p in \
    "${WHICK_MUSIC01_LOCK:-}" \
    "/data/whick-ai/2_control_center/config/solutions/music-01.json" \
    "$ROOT/../install/runtime/components.lock.json" \
    "$ROOT/live/lib/components.lock.json"; do
    [[ -n "$p" && -f "$p" ]] && { echo "$p"; return 0; }
  done
  return 1
}

lock_field() {
  local field="$1" lock
  lock="$(lock_json_path)" || return 1
  python3 - <<'PY' "$lock" "$field"
import json, sys
lock = json.load(open(sys.argv[1]))
field = sys.argv[2]
components = lock.get("components", {})
if field == "docker_deb_bundle":
    print(components.get("docker_ce", {}).get("deb_bundle", ""))
elif field == "runtime_bundle":
    print(components.get("runtime_bundle", {}).get("file", ""))
PY
}

resolve_artifact_src() {
  local name="$1"
  [[ -n "$name" ]] || return 1
  for p in \
    "${WHICK_MUSIC01_DIST:-}/$name" \
    "$ROOT/../dist/music-01/$name" \
    "/mnt/music/whick-cc/build-staging/music-01/$name" \
    "/mnt/music/whick-cc/build-staging/uab/$name" \
    "/mnt/music/whick-cc/solutions/music-01/v1.0.2/$name"; do
    [[ -n "$p" && -f "$p" ]] && { echo "$p"; return 0; }
  done
  # Registered runtime bundles may have a storage prefix while components.lock keeps
  # the canonical filename expected on customer machines.
  local match
  match="$(find /mnt/music/whick-cc/solutions/music-01 -name "*$name" -type f 2>/dev/null | sort | tail -1 || true)"
  [[ -n "$match" && -f "$match" ]] && { echo "$match"; return 0; }
  return 1
}

export WHICK_PROD_INSTALL="${WHICK_PROD_INSTALL:-1}"
STAMP="$(date +%Y%m%d)"
BUILD_STAMP="$(date +%Y%m%d%H)"
VERSION_FILE=""
case "${WHICK_USB_PROFILE:-full}" in
  wired|full)
    VERSION_FILE="/data/whick-ai/2_control_center/config/solutions/connect-wired.json"
    ;;
  wireless)
    VERSION_FILE="/data/whick-ai/2_control_center/config/solutions/connect-wireless.json"
    ;;
esac
CONNECT_VERSION="${WHICK_CONNECT_VERSION:-}"
if [[ -z "$CONNECT_VERSION" && -n "$VERSION_FILE" && -f "$VERSION_FILE" ]]; then
  CONNECT_VERSION="$(python3 -c "import json; print(json.load(open('$VERSION_FILE'))['version'])")"
fi
if [[ -z "$CONNECT_VERSION" && -f "$ROOT/connect-wired.version.json" ]]; then
  CONNECT_VERSION="$(python3 -c "import json; print(json.load(open('$ROOT/connect-wired.version.json'))['version'])")"
fi
PACKAGE_SOLUTION_CODE="${SOLUTION_CODE:-connect-wired}"
if [[ -n "$VERSION_FILE" && -f "$VERSION_FILE" ]]; then
  PACKAGE_SOLUTION_CODE="$(python3 -c "import json; print(json.load(open('$VERSION_FILE'))['solution_code'])")"
fi
OUT="${WHICK_CONNECT_DIST:-/mnt/music/whick-cc/build-staging/connect-usb}"
CONNECT_ZIP_NAME="${WHICK_CONNECT_ZIP_NAME:-USB설치용.zip}"
CONNECT_PKG_NAME="${WHICK_CONNECT_PKG_NAME:-connect-usb-pkg}"
# USB = 연동(1~4)만. bootstrap/docker/runtime 은 전부 CC 원격 제공 (오프라인 모드 없음)
# 레거시 env 무시 — WHICK_USB_ARTIFACT_MODE=full|slim 삭제됨
if [[ -n "${WHICK_USB_ARTIFACT_MODE:-}" ]]; then
  echo "WARN: WHICK_USB_ARTIFACT_MODE=${WHICK_USB_ARTIFACT_MODE} ignored (offline/full USB mode removed — CC-only)" >&2
fi
PKG="$OUT/$CONNECT_PKG_NAME"
ALPINE_VER="${WHICK_ALPINE_VER:-3.21.7}"
ALPINE_BRANCH="${WHICK_ALPINE_BRANCH:-${ALPINE_VER%.*}}"

rm -rf "$PKG"
mkdir -p "$PKG/whick-boot-connect" "$OUT/cache"

echo "==> apkovl (Alpine ${ALPINE_VER} — live mini tools + whick-boot-connect)"
APKOVL_STAGE="$(mktemp -d)"
APKOVL_OUT="$(mktemp -d)"
trap 'rm -rf "$APKOVL_STAGE" "$APKOVL_OUT"' EXIT
mkdir -p "$APKOVL_STAGE/etc/local.d" "$APKOVL_STAGE/etc/apk/protected_paths.d"
mkdir -p "$APKOVL_STAGE/etc/runlevels/default" "$APKOVL_STAGE/etc/runlevels/boot" "$APKOVL_STAGE/etc/init.d"
WHICK_USB_PROFILE="${WHICK_USB_PROFILE:-full}"
LOCAL_START="$BC/alpine-local.d-whick-connect.start"
INITTAB_SRC="$BC/apkovl-inittab"
APKOVL_SCRIPTS=(whick-boot-sequence.sh whick-customer-setup.py whick-boot-connect.sh whick-setup-supervisor.sh error_guide.py i18n_msg.py cc_client.py cc_install_ws.py hw_identity.py)
APKOVL_EXTRA=(whick-headless-console.sh whick-tty-keeper.sh)

sed -e "s/@WHICK_BUILD@/$BUILD_STAMP/g" -e "s/@WHICK_VERSION@/${CONNECT_VERSION:-dev}/g" "$LOCAL_START" \
  >"$APKOVL_STAGE/etc/local.d/whick-connect.start"
if [[ "$WHICK_USB_PROFILE" == "wired" ]]; then
  sed -i 's/(kernel 6.12 · 8125.*)/(wired LAN · kernel 6.12)/' "$APKOVL_STAGE/etc/local.d/whick-connect.start"
elif [[ "$WHICK_USB_PROFILE" == "wireless" ]]; then
  sed -i 's/(kernel 6.12 · 8125.*)/(wireless Wi-Fi · kernel 6.12)/' "$APKOVL_STAGE/etc/local.d/whick-connect.start"
fi
chmod +x "$APKOVL_STAGE/etc/local.d/whick-connect.start"
cp "$BC/alpine-init.d-whick-modloop" "$APKOVL_STAGE/etc/init.d/whick-modloop"
chmod +x "$APKOVL_STAGE/etc/init.d/whick-modloop"
cp "$BC/alpine-init.d-whick-no-login" "$APKOVL_STAGE/etc/init.d/whick-no-login"
chmod +x "$APKOVL_STAGE/etc/init.d/whick-no-login"
ln -sf /etc/init.d/local "$APKOVL_STAGE/etc/runlevels/default/local"
ln -sf /etc/init.d/whick-modloop "$APKOVL_STAGE/etc/runlevels/boot/whick-modloop"
ln -sf /etc/init.d/whick-no-login "$APKOVL_STAGE/etc/runlevels/boot/whick-no-login"
cp "$INITTAB_SRC" "$APKOVL_STAGE/etc/inittab"
printf '%s\n' '!etc/inittab' >"$APKOVL_STAGE/etc/apk/protected_paths.d/whick.list"
mkdir -p "$APKOVL_STAGE/opt/whick-boot-connect/templates"
for f in "${APKOVL_SCRIPTS[@]}"; do
  [ -f "$BC/$f" ] && cp "$BC/$f" "$APKOVL_STAGE/opt/whick-boot-connect/"
done
for f in "${APKOVL_EXTRA[@]}"; do
  [ -f "$BC/$f" ] && cp "$BC/$f" "$APKOVL_STAGE/opt/whick-boot-connect/"
done
cp "$BC/templates/install.html" "$APKOVL_STAGE/opt/whick-boot-connect/templates/"
chmod +x "$APKOVL_STAGE/opt/whick-boot-connect/"*.sh "$APKOVL_STAGE/opt/whick-boot-connect/"*.py 2>/dev/null || true

chmod +x "$APKOVL_STAGE/opt/whick-boot-connect/"*.sh "$APKOVL_STAGE/opt/whick-boot-connect/"*.py 2>/dev/null || true
cp "$BC/whick-env.sh" "$APKOVL_STAGE/opt/whick-boot-connect/"
if [[ "${WHICK_PROD_INSTALL:-0}" == "1" ]]; then
  if ! grep -q '^export WHICK_PROD_INSTALL=' "$APKOVL_STAGE/opt/whick-boot-connect/whick-env.sh"; then
    echo 'export WHICK_PROD_INSTALL=1' >>"$APKOVL_STAGE/opt/whick-boot-connect/whick-env.sh"
  else
    sed -i 's/^export WHICK_PROD_INSTALL=.*/export WHICK_PROD_INSTALL=1/' \
      "$APKOVL_STAGE/opt/whick-boot-connect/whick-env.sh" 2>/dev/null || \
      sed -i 's/^WHICK_PROD_INSTALL=.*/export WHICK_PROD_INSTALL=1/' \
      "$APKOVL_STAGE/opt/whick-boot-connect/whick-env.sh"
  fi
  # bootstrap rootfs · docker · runtime → USB/apkovl 미포함 (CC /install/bootstrap/artifact)
  echo "prod: large install payloads omitted from USB — CC fetch at deploy/firstboot"
else
  sed -i 's/^export WHICK_PROD_INSTALL=.*/export WHICK_PROD_INSTALL=0/' \
    "$APKOVL_STAGE/opt/whick-boot-connect/whick-env.sh" 2>/dev/null || \
    sed -i 's/^WHICK_PROD_INSTALL=.*/export WHICK_PROD_INSTALL=0/' \
    "$APKOVL_STAGE/opt/whick-boot-connect/whick-env.sh"
  if ! grep -q '^export WHICK_LINUX_INSTALL_DRY_RUN=' "$APKOVL_STAGE/opt/whick-boot-connect/whick-env.sh"; then
    echo 'export WHICK_LINUX_INSTALL_DRY_RUN=1' >>"$APKOVL_STAGE/opt/whick-boot-connect/whick-env.sh"
  else
    sed -i 's/^export WHICK_LINUX_INSTALL_DRY_RUN=.*/export WHICK_LINUX_INSTALL_DRY_RUN=1/' \
      "$APKOVL_STAGE/opt/whick-boot-connect/whick-env.sh" 2>/dev/null || true
  fi
  echo "dev/lab USB: WHICK_PROD_INSTALL=0 dry-run partition preview"
fi

# 호출자가 지정한 CC 주소·bootstrap secret을 산출물에 고정한다.
# 테스트 USB wrapper가 이 경로로 test-admin + test 전용 secret을 주입한다.
pin_whick_env() {
  local key="$1" value="$2"
  python3 - "$APKOVL_STAGE/opt/whick-boot-connect/whick-env.sh" "$key" "$value" <<'PY'
import pathlib, shlex, sys
path, key, value = pathlib.Path(sys.argv[1]), sys.argv[2], sys.argv[3]
lines = [
    line for line in path.read_text(encoding="utf-8").splitlines()
    if not line.startswith(f"export {key}=")
]
lines.append(f"export {key}={shlex.quote(value)}")
path.write_text("\n".join(lines) + "\n", encoding="utf-8")
PY
}
if [[ -n "${WHICK_CC_API_URL:-}" ]]; then
  pin_whick_env WHICK_CC_API_URL "$WHICK_CC_API_URL"
  pin_whick_env WHICK_CANONICAL_CC_API_URL "${WHICK_CANONICAL_CC_API_URL:-$WHICK_CC_API_URL}"
fi
if [[ -n "${WHICK_INSTALL_BOOTSTRAP_SECRET:-}" ]]; then
  pin_whick_env WHICK_INSTALL_BOOTSTRAP_SECRET "$WHICK_INSTALL_BOOTSTRAP_SECRET"
fi
if [[ -n "${WHICK_ALLOW_NON_TUNNEL_CC:-}" ]]; then
  pin_whick_env WHICK_ALLOW_NON_TUNNEL_CC "$WHICK_ALLOW_NON_TUNNEL_CC"
fi

cp "$BC/whick-kernel-modules.sh" "$APKOVL_STAGE/opt/whick-boot-connect/"
chmod +x "$APKOVL_STAGE/opt/whick-boot-connect/whick-env.sh"
chmod +x "$APKOVL_STAGE/opt/whick-boot-connect/whick-kernel-modules.sh"

echo "==> USB 연동(1~4) only — phase 5~7은 CC 서버 bundle (apkovl 미포함)"
cat >"$APKOVL_STAGE/opt/whick-boot-connect/REMOTE-PHASES-CC.txt" <<'EOF'
Whick USB = 초기 연동(1~4) only. 오프라인 설치 없음.
Phase 5~7: GET /install/bootstrap/phase-bundle
bootstrap / docker / runtime: GET /install/bootstrap/artifact/...
EOF

WHICK_APK_PKGS="python3 ca-certificates curl dmidecode iproute2 exfat-utils ntfs-3g wpa_supplicant wireless-tools openssl iw e2fsprogs wireless-regdb util-linux-misc lsblk findmnt sfdisk blkid bash parted"
WHICK_FW_PKGS="linux-firmware linux-firmware-intel linux-firmware-rtlwifi"
if [[ "${WHICK_PROD_INSTALL:-0}" == "1" ]]; then
  WHICK_APK_PKGS="$WHICK_APK_PKGS grub grub-efi"
fi
case "$WHICK_USB_PROFILE" in
  wired)
    WHICK_APK_PKGS="python3 ca-certificates curl dmidecode iproute2 exfat-utils ntfs-3g openssl e2fsprogs util-linux-misc lsblk findmnt sfdisk blkid bash parted"
    if [[ "${WHICK_PROD_INSTALL:-0}" == "1" ]]; then
      WHICK_APK_PKGS="$WHICK_APK_PKGS grub grub-efi"
    fi
    WHICK_FW_PKGS=""
    WHICK_ETH_FW=1
    CONNECT_ZIP_NAME="${WHICK_CONNECT_ZIP_NAME:-USB설치용-유선.zip}"
    ;;
  wireless)
    WHICK_APK_PKGS="python3 ca-certificates curl dmidecode iproute2 exfat-utils ntfs-3g wpa_supplicant wireless-tools openssl iw e2fsprogs wireless-regdb util-linux-misc lsblk findmnt sfdisk blkid bash parted"
    if [[ "${WHICK_PROD_INSTALL:-0}" == "1" ]]; then
      WHICK_APK_PKGS="$WHICK_APK_PKGS grub grub-efi"
    fi
    WHICK_FW_PKGS="linux-firmware linux-firmware-intel linux-firmware-rtlwifi"
    CONNECT_ZIP_NAME="${WHICK_CONNECT_ZIP_NAME:-USB설치용-무선.zip}"
    ;;
esac
echo "USB profile: $WHICK_USB_PROFILE → $CONNECT_ZIP_NAME"
docker run --rm \
  -v "$APKOVL_STAGE:/staging:ro" \
  -v "$APKOVL_OUT:/out" \
  "alpine:${ALPINE_VER}" \
  sh -ce "
    set -e
    cp -a /staging/etc/. /etc/
    cp -a /staging/opt/. /opt/
    MINI=/opt/whick-boot-connect/mini
    mkdir -p \"\$MINI/etc/apk\"
    cp -a /etc/apk/repositories /etc/apk/keys \"\$MINI/etc/apk/\"
    apk add --root \"\$MINI\" --initdb --no-cache $WHICK_APK_PKGS
    if [ -n \"$WHICK_FW_PKGS\" ]; then
      apk add --no-cache $WHICK_FW_PKGS
      mkdir -p /opt/whick-boot-connect/firmware
      cp -a /lib/firmware/. /opt/whick-boot-connect/firmware/
    elif [ -n \"${WHICK_ETH_FW:-}\" ]; then
      # 빌드 컨테이너에만 full meta 설치 — apkovl에는 선택 디렉터리만 복사
      apk add --no-cache linux-firmware
      mkdir -p /opt/whick-boot-connect/firmware/intel
      cp -a /lib/firmware/rtl_nic /opt/whick-boot-connect/firmware/
      [ -d /lib/firmware/intel/ice ] && cp -a /lib/firmware/intel/ice /opt/whick-boot-connect/firmware/intel/
      [ -d /lib/firmware/intel/igc ] && cp -a /lib/firmware/intel/igc /opt/whick-boot-connect/firmware/intel/
      [ -d /lib/firmware/e100 ] && cp -a /lib/firmware/e100 /opt/whick-boot-connect/firmware/
      [ -d /lib/firmware/bnx2 ] && cp -a /lib/firmware/bnx2 /opt/whick-boot-connect/firmware/
      [ -d /lib/firmware/bnx2x ] && cp -a /lib/firmware/bnx2x /opt/whick-boot-connect/firmware/
    fi
    echo \"$WHICK_USB_PROFILE\" > /opt/whick-boot-connect/net-profile
    # etc·opt 만 overlay — usr/bin/sbin 덮어쓰면 Live fsck(libmount) 깨짐
    tar -C / -czf /out/alpine.apkovl.tar.gz etc opt
    tar -tzf /out/alpine.apkovl.tar.gz | grep -q 'opt/whick-boot-connect/mini/usr/bin/python3' || exit 1
    if [ -n \"$WHICK_FW_PKGS\" ]; then
      tar -tzf /out/alpine.apkovl.tar.gz | grep -q 'opt/whick-boot-connect/firmware/' || exit 1
    elif [ -n \"${WHICK_ETH_FW:-}\" ]; then
      tar -tzf /out/alpine.apkovl.tar.gz | grep -q 'opt/whick-boot-connect/firmware/rtl_nic/' || exit 1
      tar -tzf /out/alpine.apkovl.tar.gz | grep -q 'rtl_bt' && exit 1 || true
    else
      tar -tzf /out/alpine.apkovl.tar.gz | grep -q 'opt/whick-boot-connect/net-profile' || exit 1
    fi
    tar -tzf /out/alpine.apkovl.tar.gz | grep -q '^lib/' && exit 1 || true
    tar -tzf /out/alpine.apkovl.tar.gz | grep -q '^usr/' && exit 1 || true
    tar -tzf /out/alpine.apkovl.tar.gz | grep -q '^sbin/' && exit 1 || true
    tar -tzf /out/alpine.apkovl.tar.gz | grep -q '^bin/' && exit 1 || true
    tar -tzf /out/alpine.apkovl.tar.gz | grep -q 'runlevels/boot/local' && exit 1 || true
    tar -tzf /out/alpine.apkovl.tar.gz | grep -q 'runlevels/boot/whick-modloop' || exit 1
    tar -tzf /out/alpine.apkovl.tar.gz | grep -q 'opt/whick-boot-connect/mini/bin/lsblk' || exit 1
    tar -tzf /out/alpine.apkovl.tar.gz | grep -q 'opt/whick-boot-connect/REMOTE-PHASES-CC.txt' || exit 1
    tar -tzf /out/alpine.apkovl.tar.gz | grep -q 'opt/whick-boot-connect/phases/' && exit 1 || true
    tar -tzf /out/alpine.apkovl.tar.gz | grep -q 'opt/whick-boot-connect/mini/bin/bash' || exit 1
    echo \"apkovl: \$(du -h /out/alpine.apkovl.tar.gz | awk '{print \$1}')\"
  "
cp -f "$APKOVL_OUT/alpine.apkovl.tar.gz" "$PKG/alpine.apkovl.tar.gz"
echo "apkovl: USB·ISO용 alpine.apkovl.tar.gz 1개 (whick.apkovl 중복 제거 — zip 용량 절감)"

if [[ "${WHICK_CONNECT_APKOVL_ONLY:-0}" == "1" ]]; then
  echo ""
  echo "OK  apkovl-only → $PKG/alpine.apkovl.tar.gz ($(du -h "$PKG/alpine.apkovl.tar.gz" | awk '{print $1}'))"
  echo "    (ISO·zip·Ventoy 생략 — preflight-connect.sh)"
  exit 0
fi

echo "==> boot-connect scripts"
cp "$BC/whick-boot-connect.sh" "$PKG/whick-boot-connect/"
chmod +x "$PKG/whick-boot-connect/whick-boot-connect.sh"
chmod +x "$ROOT/whick-boot-sequence.sh" "$ROOT/whick-customer-setup.py" 2>/dev/null || true
cp "$BC/whick-boot-sequence.sh" "$PKG/whick-boot-connect/"
chmod +x "$PKG/whick-boot-connect/whick-boot-sequence.sh"
cp "$BC/whick-customer-setup.py" "$PKG/whick-boot-connect/"
cp "$BC/whick-setup-supervisor.sh" "$PKG/whick-boot-connect/"
cp "$BC/whick-headless-console.sh" "$PKG/whick-boot-connect/"
cp "$BC/whick-tty-keeper.sh" "$PKG/whick-boot-connect/"
chmod +x "$PKG/whick-boot-connect/whick-tty-keeper.sh"
cp "$BC/error_guide.py" "$PKG/whick-boot-connect/"
cp "$BC/hw_identity.py" "$PKG/whick-boot-connect/"
cp "$BC/cc_client.py" "$PKG/whick-boot-connect/"
cp "$BC/cc_install_ws.py" "$PKG/whick-boot-connect/"
chmod +x "$PKG/whick-boot-connect/whick-customer-setup.py"
chmod +x "$PKG/whick-boot-connect/whick-setup-supervisor.sh"

cp "$APKOVL_STAGE/opt/whick-boot-connect/whick-env.sh" "$PKG/whick-boot-connect/"
# components.lock.json — SSD deploy prefetch (docker/runtime artifact resolution)
LOCK_SRC="$(lock_json_path 2>/dev/null)" || LOCK_SRC=""
if [[ -n "$LOCK_SRC" && -f "$LOCK_SRC" ]]; then
  mkdir -p "$PKG/whick-boot-connect/lib"
  cp -f "$LOCK_SRC" "$PKG/whick-boot-connect/lib/components.lock.json"
  echo "lock: components.lock.json in whick-boot-connect/lib/"
fi
if [[ "${WHICK_PROD_INSTALL:-0}" == "1" ]]; then
  # lock만 USB — 실제 bootstrap/docker/runtime 파일은 CC에서 다운로드
  DOCKER_BUNDLE="$(lock_field docker_deb_bundle 2>/dev/null || true)"
  RUNTIME_BUNDLE="$(lock_field runtime_bundle 2>/dev/null || true)"
  echo "prod: CC-only payloads (not in zip)"
  [[ -n "$DOCKER_BUNDLE" ]] && echo "  docker → CC: $DOCKER_BUNDLE"
  [[ -n "$RUNTIME_BUNDLE" ]] && echo "  runtime → CC: $RUNTIME_BUNDLE"
  echo "  bootstrap → CC: whick-bootstrap-rootfs.tar.xz"
  printf '%s\n' "cc-server" >"$PKG/whick-boot-connect/USB-ARTIFACT-MODE.txt"
fi

echo "==> USB zip — CC-connected install (phases 1~4 on USB · 5~7 from server)"
cp "$APKOVL_STAGE/opt/whick-boot-connect/REMOTE-PHASES-CC.txt" "$PKG/whick-boot-connect/" 2>/dev/null ||   cp -f "$BC/../docs/INITIAL-INTEGRATION-PHASE.md" "$PKG/whick-boot-connect/REMOTE-PHASES-CC.txt" 2>/dev/null || true
cat >"$PKG/whick-boot-connect/CC-SERVER-INSTALL.txt" <<'EOF'
Whick 고객 USB = 중앙서버(CC) 연결 필수. 오프라인 설치 없음.

USB에 포함:
- Alpine Live ISO + apkovl (부트·연동 UI·미니 도구)
- Ventoy / Windows Maker

USB에 없음 (설치 중 CC에서 받음):
- Ubuntu bootstrap rootfs
- Docker CE deb bundle
- music-01 runtime bundle

Phase 1~4 = USB (부트·네트워크·하드웨어·동의·등록)
Phase 5~7 = CC phase-bundle + artifact download
EOF
# 레거시 파일명 호환 (구 테스트/문서 참조)
cp -f "$PKG/whick-boot-connect/CC-SERVER-INSTALL.txt" "$PKG/whick-boot-connect/OFFLINE-OS-INSTALL.txt"

mkdir -p "$PKG/whick-boot-connect/templates"
cp "$BC/templates/install.html" "$PKG/whick-boot-connect/templates/"
echo "$WHICK_USB_PROFILE" >"$PKG/whick-boot-connect/net-profile"
if [[ -n "${CONNECT_VERSION:-}" ]]; then
  cat >"$PKG/whick-package.json" <<EOF
{
  "solution_code": "$PACKAGE_SOLUTION_CODE",
  "version": "$CONNECT_VERSION",
  "profile": "$WHICK_USB_PROFILE",
  "build": "$BUILD_STAMP"
}
EOF
fi

echo "==> Windows Maker (ISO → USB DD, no Ventoy)"
cp "$ROOT/windows/make-usb.bat" "$PKG/"
python3 - <<PY
from pathlib import Path
src = Path("$ROOT/windows/Whick-USB-Maker.ps1")
dst = Path("$PKG/Whick-USB-Maker.ps1")
data = src.read_bytes()
if not data.startswith(b"\xef\xbb\xbf"):
    data = b"\xef\xbb\xbf" + data
dst.write_bytes(data)
print("Whick-USB-Maker.ps1 (UTF-8 BOM)")
PY

cp -f "$ROOT/docs/USB-고객안내.txt" "$PKG/" 2>/dev/null || true
cp -f "$ROOT/docs/USB-저작권-배포안내.txt" "$PKG/" 2>/dev/null || true
case "$WHICK_USB_PROFILE" in
  wired)
    cp -f "$ROOT/docs/USB-고객안내-유선.txt" "$PKG/USB-고객안내.txt" 2>/dev/null || true
    ;;
  wireless)
    cp -f "$ROOT/docs/USB-고객안내-무선.txt" "$PKG/USB-고객안내.txt" 2>/dev/null || true
    ;;
esac

ALPINE_VARIANT="${WHICK_ALPINE_VARIANT:-standard}"
ALPINE_ISO="alpine-${ALPINE_VARIANT}-${ALPINE_VER}-x86_64.iso"
ALPINE_PATH="$OUT/cache/$ALPINE_ISO"
if [[ ! -f "$ALPINE_PATH" ]]; then
  echo "==> download Alpine $ALPINE_VER $ALPINE_VARIANT"
  curl -fsSL -o "$ALPINE_PATH" \
    "https://dl-cdn.alpinelinux.org/alpine/v${ALPINE_BRANCH}/releases/x86_64/$ALPINE_ISO"
fi
echo "==> patch alpine-live.iso (apkovl embedded in ISO root — Maker DD writes this ISO)"
chmod +x "$ROOT/scripts/patch-alpine-live-iso.sh"
"$ROOT/scripts/patch-alpine-live-iso.sh" "$ALPINE_PATH" "$PKG/alpine-live.iso" "$PKG/alpine.apkovl.tar.gz"
sha256sum "$PKG/alpine-live.iso" | awk '{print $1}' > "$PKG/alpine-live.iso.sha256"
echo "alpine-live.iso ($ALPINE_VARIANT) sha256: $(cat "$PKG/alpine-live.iso.sha256")"

rm -f "$PKG/whick.apkovl.tar.gz"
# Maker no longer needs separate USB-side apkovl/ventoy — ISO embeds apkovl.
# Keep alpine.apkovl.tar.gz in zip for inspect/debug only (optional small overhead).

# Hard fail: USB package must not ship rescue materials
RESCUE_HITS="$(find "$PKG" \( -iname '*whick-rescue*' -o -path '*/rescue/*' \) 2>/dev/null | head -n 20 || true)"
if [[ -n "$RESCUE_HITS" ]]; then
  echo "FATAL: rescue materials found under package:" >&2
  echo "$RESCUE_HITS" >&2
  exit 1
fi
echo "OK: package has no rescue materials"

ZIP="$OUT/$CONNECT_ZIP_NAME"
python3 - <<PY
import zipfile
from pathlib import Path
pkg = Path("$PKG")
out = Path("$ZIP")
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for f in sorted(pkg.rglob("*")):
        if f.is_file():
            z.write(f, f.relative_to(pkg))
print("OK", out, f"{out.stat().st_size/1024/1024:.1f} MiB")
PY

echo ""
echo "OK  $ZIP"
echo "    VIP / Windows 고객 배포용"
echo "    로컬 USB: unzip 후 make-usb.bat (관리자) — alpine-live.iso DD 기록"
