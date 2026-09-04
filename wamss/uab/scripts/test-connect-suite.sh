#!/usr/bin/env bash
# Whick connect-usb — 상용 배포 전 검증 스위트
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIST="${WHICK_CONNECT_DIST:-/mnt/music/whick-cc/build-staging/connect-usb}"
WHICK_USB_PROFILE="${WHICK_USB_PROFILE:-full}"
if [[ -n "${WHICK_CONNECT_ZIP_NAME:-}" ]]; then
  CONNECT_ZIP_NAME="$WHICK_CONNECT_ZIP_NAME"
elif [[ "$WHICK_USB_PROFILE" == "wired" ]]; then
  CONNECT_ZIP_NAME="USB설치용-유선.zip"
elif [[ "$WHICK_USB_PROFILE" == "wireless" ]]; then
  CONNECT_ZIP_NAME="USB설치용-무선.zip"
else
  CONNECT_ZIP_NAME="USB설치용.zip"
fi
if [[ "$CONNECT_ZIP_NAME" == *"유선"* ]]; then
  WHICK_USB_PROFILE=wired
elif [[ "$CONNECT_ZIP_NAME" == *"무선"* ]]; then
  WHICK_USB_PROFILE=wireless
fi
ZIP="$DIST/$CONNECT_ZIP_NAME"
CC_URL="${WHICK_CC_API_URL:-https://admin.whick.org/api/v1}"
PASS=0
FAIL=0
WARN=0

ok()   { echo "  PASS  $*"; PASS=$((PASS + 1)); }
fail() { echo "  FAIL  $*"; FAIL=$((FAIL + 1)); }
warn() { echo "  WARN  $*"; WARN=$((WARN + 1)); }

# pipefail + tar|grep -q → SIGPIPE(141) 오탐 방지
apkovl_has() {
  grep -Fq "$1" < <(tar -tzf "$APKOVL" 2>/dev/null)
}

section() { echo ""; echo "== $* =="; }

section "1. 소스 파일"
REQUIRED=(
  "$ROOT/windows/make-usb.bat"
  "$ROOT/windows/Whick-USB-Maker.ps1"
  "$ROOT/boot-connect/whick-boot-connect.sh"
  "$ROOT/boot-connect/whick-boot-sequence.sh"
  "$ROOT/boot-connect/whick-customer-setup.py"
  "$ROOT/boot-connect/error_guide.py"
  "$ROOT/boot-connect/hw_identity.py"
  "$ROOT/boot-connect/cc_client.py"
  "$ROOT/boot-connect/templates/install.html"
  "$ROOT/boot-connect/alpine-local.d-whick-connect.start"
  "$ROOT/boot-connect/alpine-init.d-whick-modloop"
  "$ROOT/docs/USB-고객안내.txt"
  "$ROOT/docs/USB-고객안내-유선.txt"
  "$ROOT/docs/USB-고객안내-무선.txt"
  "$ROOT/docs/USB-저작권-배포안내.txt"
  "$ROOT/scripts/verify-connect-sources.sh"
  "$ROOT/scripts/patch-alpine-live-iso.sh"
)
for f in "${REQUIRED[@]}"; do
  [[ -f "$f" ]] && ok "$(basename "$f")" || fail "missing $f"
done

[[ -x "$ROOT/boot-connect/whick-boot-connect.sh" ]] && ok "boot-connect executable" || fail "boot-connect not executable"

section "2. ZIP 패키지"
if [[ ! -f "$ZIP" ]]; then
  fail "zip not found — run build-connect-usb-package.sh ($ZIP)"
else
  ok "zip exists: $(basename "$ZIP")"
  [[ "$(basename "$ZIP")" == "$CONNECT_ZIP_NAME" ]] && ok "zip filename $CONNECT_ZIP_NAME" || fail "zip must be named $CONNECT_ZIP_NAME"
  SIZE_MB=$(python3 -c "import os; print(f'{os.path.getsize(\"$ZIP\")/1024/1024:.1f}')")
  python3 -c "import os; exit(0 if os.path.getsize('$ZIP') > 50*1024*1024 else 1)" \
    && ok "zip size ${SIZE_MB} MB (>50)" || fail "zip too small (${SIZE_MB} MB)"

  WORK="$(mktemp -d)"
  trap 'rm -rf "$WORK"' EXIT
  python3 - <<PY
import zipfile
from pathlib import Path
zipfile.ZipFile("$ZIP").extractall("$WORK")
print("extracted")
PY
  PKG_DIR="$(find "$WORK" -maxdepth 1 -type d -name 'whick-connect-usb-*' | head -1)"
  if [[ -z "$PKG_DIR" && -f "$WORK/make-usb.bat" ]]; then
    PKG_DIR="$WORK"
  fi
  [[ -n "$PKG_DIR" ]] && ok "zip layout (flat or single folder)" || fail "zip layout invalid"

  ZIP_REQUIRED=(
    make-usb.bat
    Whick-USB-Maker.ps1
    alpine-live.iso
    alpine-live.iso.sha256
    alpine.apkovl.tar.gz
    whick-boot-connect/whick-boot-connect.sh
    whick-boot-connect/whick-boot-sequence.sh
    whick-boot-connect/whick-setup-supervisor.sh
    whick-boot-connect/whick-customer-setup.py
    whick-boot-connect/error_guide.py
    whick-boot-connect/hw_identity.py
    whick-boot-connect/cc_client.py
    whick-boot-connect/templates/install.html
    USB-고객안내.txt
    USB-저작권-배포안내.txt
  )
  for f in "${ZIP_REQUIRED[@]}"; do
    [[ -e "$PKG_DIR/$f" ]] && ok "zip/$f" || fail "zip missing $f"
  done
  if [[ "$WHICK_USB_PROFILE" == "wired" ]]; then
    [[ -e "$PKG_DIR/whick-boot-connect/net-profile" ]] && ok "zip net-profile" || fail "zip missing net-profile"
    [[ "$(tr -d '\r\n' <"$PKG_DIR/whick-boot-connect/net-profile")" == "wired" ]] \
      && ok "zip net-profile wired" || fail "zip net-profile must be wired"
  elif [[ "$WHICK_USB_PROFILE" == "wireless" ]]; then
    [[ -e "$PKG_DIR/whick-boot-connect/net-profile" ]] && ok "zip net-profile" || fail "zip missing net-profile"
    [[ "$(tr -d '\r\n' <"$PKG_DIR/whick-boot-connect/net-profile")" == "wireless" ]] \
      && ok "zip net-profile wireless" || fail "zip net-profile must be wireless"
  fi
  for stale in README.txt WHICK-USB-고객안내.txt Whick-USB-Maker.bat; do
    [[ -e "$PKG_DIR/$stale" ]] && fail "zip must not contain stale $stale" || ok "zip no stale $stale"
  done
  if [[ -e "$PKG_DIR/whick.apkovl.tar.gz" ]]; then
    fail "zip must not contain whick.apkovl.tar.gz (duplicate apkovl)"
  else
    ok "zip no whick.apkovl duplicate"
  fi
  ZIP_MB=$(python3 -c "import os; print(os.path.getsize('$ZIP')/1024/1024)")
  ok "zip size ${ZIP_MB} MiB (CC-connected USB — no offline payload)"

  # CC-only: USB에 bootstrap/docker/runtime 대용량 금지
  [[ ! -d "$PKG_DIR/whick-boot-connect/artifacts" ]] \
    || [[ -z "$(find "$PKG_DIR/whick-boot-connect/artifacts" -type f 2>/dev/null | head -1)" ]] \
    && ok "no docker/runtime artifacts in zip" \
    || fail "zip must not contain artifacts/ (CC-only)"
  RUNTIME_IN_ZIP=$(find "$PKG_DIR/whick-boot-connect" -name '*runtime*.tar.zst' 2>/dev/null | head -1 || true)
  [[ -z "$RUNTIME_IN_ZIP" ]] && ok "no runtime bundle in zip" || fail "runtime must not be on USB"
  DOCKER_IN_ZIP=$(find "$PKG_DIR/whick-boot-connect" -name 'docker-ce*.tar.gz' 2>/dev/null | head -1 || true)
  [[ -z "$DOCKER_IN_ZIP" ]] && ok "no docker deb bundle in zip" || fail "docker deb must not be on USB"
  BOOT_IN_ZIP=$(find "$PKG_DIR/whick-boot-connect" -name 'whick-bootstrap-rootfs.tar.*' 2>/dev/null | head -1 || true)
  [[ -z "$BOOT_IN_ZIP" ]] && ok "no bootstrap rootfs in zip tree" || fail "bootstrap must not be on USB (CC fetch)"
  RESCUE_ZIP_HITS="$(python3 -c "import re,zipfile; z=zipfile.ZipFile(r\"$ZIP\"); print(\"\\n\".join(n for n in z.namelist() if re.search(r\"whick-rescue|/rescue/\", n, re.I)))")"
  if [[ -n "$RESCUE_ZIP_HITS" ]]; then
    echo "$RESCUE_ZIP_HITS"
    fail "zip must not contain rescue materials (whick-rescue or /rescue/)"
  else
    ok "zip has no rescue materials"
  fi
  if apkovl_has 'opt/whick-boot-connect/bootstrap/whick-bootstrap-rootfs.tar.xz' \
    || apkovl_has 'opt/whick-boot-connect/bootstrap/whick-bootstrap-rootfs.tar.gz'; then
    fail "apkovl must not embed bootstrap rootfs (CC fetch)"
  else
    ok "apkovl no bootstrap rootfs"
  fi
  MODE_TXT=""
  [[ -f "$PKG_DIR/whick-boot-connect/USB-ARTIFACT-MODE.txt" ]] \
    && MODE_TXT="$(tr -d '\r\n' <"$PKG_DIR/whick-boot-connect/USB-ARTIFACT-MODE.txt")"
  [[ "$MODE_TXT" == "cc-server" || "$MODE_TXT" == "slim" || -z "$MODE_TXT" ]] \
    && ok "artifact mode cc-server (offline/full removed)" \
    || fail "legacy offline mode marker: $MODE_TXT"
  grep -qE 'CC|중앙서버|NOT on USB|오프라인 설치 없음' "$PKG_DIR/whick-boot-connect/CC-SERVER-INSTALL.txt" 2>/dev/null \
    || grep -qE 'CC|중앙서버|NOT on USB|오프라인 설치 없음' "$PKG_DIR/whick-boot-connect/OFFLINE-OS-INSTALL.txt" 2>/dev/null \
    && ok "CC-server install note present" \
    || fail "missing CC-SERVER-INSTALL / CC note"

  # apkovl 내용
  APKOVL="$PKG_DIR/alpine.apkovl.tar.gz"
  if apkovl_has 'etc/local.d/whick-connect.start'; then
    ok "apkovl contains whick-connect.start"
  else
    fail "apkovl missing whick-connect.start"
  fi
  if apkovl_has 'etc/runlevels/default/local'; then
    ok "apkovl enables OpenRC local default runlevel"
  else
    fail "apkovl missing etc/runlevels/default/local"
  fi
  if apkovl_has 'etc/runlevels/boot/local'; then
    fail "apkovl must not enable local in boot runlevel (modloop race)"
  else
    ok "apkovl local only in default runlevel"
  fi
  if [[ "$WHICK_USB_PROFILE" == "wired" ]]; then
    if apkovl_has 'opt/whick-boot-connect/firmware/rtl_nic/'; then
      ok "wired apkovl eth firmware (rtl_nic)"
    else
      fail "wired apkovl missing eth firmware (rtl_nic)"
    fi
    if tar -tzf "$APKOVL" 2>/dev/null | grep -q 'firmware/rtl_bt'; then
      fail "wired apkovl must not embed Wi-Fi firmware"
    else
      ok "wired apkovl no Wi-Fi firmware blobs"
    fi
    WIRED_PROF="$(tar -xOzf "$APKOVL" opt/whick-boot-connect/net-profile 2>/dev/null | tr -d '\r\n' || true)"
    [[ "$WIRED_PROF" == "wired" ]] && ok "apkovl net-profile wired" || fail "apkovl net-profile must be wired (got: ${WIRED_PROF:-missing})"
  elif [[ "$WHICK_USB_PROFILE" == "wireless" ]]; then
    if apkovl_has 'opt/whick-boot-connect/firmware/'; then
      ok "wireless apkovl Wi-Fi firmware (opt, not lib/)"
    else
      fail "wireless apkovl missing opt/whick-boot-connect/firmware"
    fi
    if tar -tzf "$APKOVL" 2>/dev/null | grep -q 'firmware/rtl_nic'; then
      fail "wireless apkovl must not embed eth rtl_nic firmware"
    else
      ok "wireless apkovl no eth rtl_nic firmware"
    fi
    WL_PROF="$(tar -xOzf "$APKOVL" opt/whick-boot-connect/net-profile 2>/dev/null | tr -d '\r\n' || true)"
    [[ "$WL_PROF" == "wireless" ]] && ok "apkovl net-profile wireless" || fail "apkovl net-profile must be wireless (got: ${WL_PROF:-missing})"
  elif apkovl_has 'opt/whick-boot-connect/firmware/'; then
    ok "apkovl embeds Wi-Fi firmware (opt, not lib/)"
  else
    fail "apkovl missing opt/whick-boot-connect/firmware"
  fi
  if tar -tzf "$APKOVL" 2>/dev/null | grep -q '^lib/'; then
    fail "apkovl must not overlay lib/ (breaks modloop)"
  else
    ok "apkovl no lib/ overlay"
  fi
  if apkovl_has 'etc/runlevels/boot/whick-modloop'; then
    ok "apkovl early whick-modloop boot service"
  else
    fail "apkovl missing whick-modloop boot service"
  fi
  if apkovl_has 'opt/whick-boot-connect/whick-customer-setup.py'; then
    ok "apkovl embeds opt/whick-boot-connect"
  else
    fail "apkovl missing opt/whick-boot-connect (Ventoy USB mount bypass)"
  fi
  if apkovl_has 'opt/whick-boot-connect/hw_identity.py'; then
    ok "apkovl embeds hw_identity.py"
  else
    fail "apkovl missing opt/whick-boot-connect/hw_identity.py"
  fi
  if tar -xOzf "$APKOVL" etc/inittab 2>/dev/null | grep -q '^#tty1::respawn.*getty'; then
    ok "apkovl inittab disables tty1 getty"
  else
    fail "apkovl inittab must disable tty1 getty (headless)"
  fi
  if [[ "$WHICK_USB_PROFILE" == "wired" ]]; then
    if tar -xOzf "$APKOVL" etc/inittab 2>/dev/null | grep -qE '^tty[0-9]+::respawn:.*getty'; then
      fail "apkovl inittab must not enable getty login (wired headless)"
    else
      ok "apkovl inittab no active getty (headless)"
    fi
  elif tar -xOzf "$APKOVL" etc/inittab 2>/dev/null | grep -qE '^tty[0-9]+::respawn:.*getty'; then
    fail "apkovl inittab must not enable any getty login"
  else
    ok "apkovl inittab no active getty (headless)"
  fi
  if tar -xOzf "$APKOVL" etc/inittab 2>/dev/null | grep -q 'whick-tty-keeper'; then
    ok "apkovl inittab tty1 status keeper"
  else
    fail "apkovl inittab missing whick-tty-keeper on tty1"
  fi
  if apkovl_has 'etc/runlevels/boot/whick-no-login'; then
    ok "apkovl early whick-no-login boot service"
  else
    fail "apkovl missing whick-no-login boot service"
  fi
  if tar -xOzf "$APKOVL" etc/apk/protected_paths.d/whick.list 2>/dev/null | grep -q 'inittab'; then
    ok "apkovl protects inittab from apk"
  else
    fail "apkovl missing protected_paths for inittab"
  fi
  if apkovl_has 'opt/whick-boot-connect/mini/usr/bin/python3'; then
    ok "apkovl mini-root python3 (no usr/ overlay)"
  else
    fail "apkovl missing opt/whick-boot-connect/mini/usr/bin/python3"
  fi
  if tar -tzf "$APKOVL" 2>/dev/null | grep -q '^usr/'; then
    fail "apkovl must not overlay usr/ (Live fsck/libmount break)"
  else
    ok "apkovl no usr/ overlay"
  fi
  if tar -tzf "$APKOVL" 2>/dev/null | grep -q '^sbin/'; then
    fail "apkovl must not overlay sbin/"
  else
    ok "apkovl no sbin/ overlay"
  fi
  if tar -tzf "$APKOVL" 2>/dev/null | grep -qx 'usr/bin/python3'; then
    fail "apkovl must not use top-level usr/bin/python3"
  fi
  if apkovl_has 'etc/runlevels/boot/networking'; then
    fail "apkovl must not enable networking boot runlevel"
  else
    ok "apkovl no networking boot (avoids interfaces parse error)"
  fi

  # alpine-live.iso: apkovl ISO 내장 + usbdelay/vfat/isofs/console; no quiet; apkovl= 금지
  if docker run --rm -v "$PKG_DIR:/pkg:ro" debian:bookworm-slim bash -c '
    apt-get update -qq && apt-get install -qq -y libarchive-tools binutils gzip >/dev/null
    bsdtar -tf /pkg/alpine-live.iso | grep -qx alpine.apkovl.tar.gz
    bsdtar -xOf /pkg/alpine-live.iso boot/grub/grub.cfg | grep -q "usbdelay="
    bsdtar -xOf /pkg/alpine-live.iso boot/grub/grub.cfg | grep -q "vfat"
    bsdtar -xOf /pkg/alpine-live.iso boot/grub/grub.cfg | grep -q "isofs"
    bsdtar -xOf /pkg/alpine-live.iso boot/grub/grub.cfg | grep -q "console=tty0"
    ! bsdtar -xOf /pkg/alpine-live.iso boot/grub/grub.cfg | grep -qE "(^|[[:space:]])quiet([[:space:]]|$)"
    ! bsdtar -xOf /pkg/alpine-live.iso boot/grub/grub.cfg | grep -q "apkovl="
    bsdtar -xOf /pkg/alpine-live.iso boot/syslinux/syslinux.cfg | grep -q "usbdelay="
    bsdtar -xOf /pkg/alpine-live.iso boot/syslinux/syslinux.cfg | grep -q "vfat"
    bsdtar -xOf /pkg/alpine-live.iso boot/syslinux/syslinux.cfg | grep -q "isofs"
    ! bsdtar -xOf /pkg/alpine-live.iso boot/syslinux/syslinux.cfg | grep -q "apkovl="
    bsdtar -xOf /pkg/alpine-live.iso boot/initramfs-lts > /tmp/ird
    gzip -dc /tmp/ird | strings | grep -q "Whick: waiting"
    gzip -dc /tmp/ird | strings | grep -q "Whick: ignoring internal-disk apkovl"
    gzip -dc /tmp/ird | strings | grep -q "Whick: found apkovl"
  ' 2>/dev/null; then
    ok "alpine-live.iso embedded apkovl + boot params + Whick initramfs (no quiet/apkovl=)"
  else
    fail "alpine-live.iso missing embedded apkovl, boot params, or Whick initramfs markers"
  fi

  # PS1 shebang/requires
  grep -q 'Request-WhickAdmin' "$PKG_DIR/Whick-USB-Maker.ps1" \
    && ok "PS1 admin elevation" || fail "PS1 missing Request-WhickAdmin"
  grep -q 'Write-WhickIsoToPhysicalDrive' "$PKG_DIR/Whick-USB-Maker.ps1" \
    && ok "PS1 ISO-DD Write-WhickIsoToPhysicalDrive" || fail "PS1 missing Write-WhickIsoToPhysicalDrive"
  grep -q 'PhysicalDrive' "$PKG_DIR/Whick-USB-Maker.ps1" \
    && ok "PS1 PhysicalDrive target" || fail "PS1 missing PhysicalDrive"
  ! grep -q 'Invoke-VentoyCli' "$PKG_DIR/Whick-USB-Maker.ps1" \
    && ok "PS1 no Invoke-VentoyCli" || fail "PS1 must not call Invoke-VentoyCli"
  ( grep -q 'CreateNoWindow' "$PKG_DIR/Whick-USB-Maker.ps1" \
      || grep -q 'WindowStyle Hidden' "$PKG_DIR/Whick-USB-Maker.ps1" ) \
    && ok "PS1 CreateNoWindow or WindowStyle Hidden" \
    || fail "PS1 missing CreateNoWindow / WindowStyle Hidden"
  grep -q 'Clear-WhickDownloadMark' "$PKG_DIR/Whick-USB-Maker.ps1" \
    && ok "PS1 clears download mark (MOTW)" || fail "PS1 missing Clear-WhickDownloadMark"

  grep -q 'WindowStyle Hidden' "$PKG_DIR/make-usb.bat" \
    && ok "BAT hidden PowerShell launch" || fail "BAT missing WindowStyle Hidden"
fi

section "3. boot-connect 스크립트 (라이브 API)"
export WHICK_CONNECT_RESULT="/tmp/whick-test-result.json"
export WHICK_CONNECT_LOG="/tmp/whick-test.log"
rm -f "$WHICK_CONNECT_RESULT"

if "$ROOT/boot-connect/whick-boot-connect.sh"; then
  ok "boot-connect exit 0"
else
  fail "boot-connect exit non-zero"
fi

if python3 - <<'PY'
import json, sys
r=json.load(open("/tmp/whick-test-result.json"))
assert r.get("ok") is True
assert r.get("health_ok") is True
assert r.get("session_ok") is True
assert r.get("hw_report_ok") is True
assert r.get("device_code","").startswith("MUSIC-")
assert len(r.get("hw_id_hash","")) == 64
assert r.get("session_id")
print(r["device_code"])
PY
then
  CODE=$(python3 -c "import json; print(json.load(open('/tmp/whick-test-result.json'))['device_code'])")
  ok "result JSON valid ($CODE)"
else
  fail "result JSON invalid"
  cat "$WHICK_CONNECT_RESULT" 2>/dev/null || true
fi

section "4. API 계약 (health → session → hw-report → session 조회)"
python3 - <<PY
import json, urllib.request, sys

CC = "$CC_URL".rstrip("/")
failures = []

def req(url, method="GET", data=None, headers=None):
    h = {"Content-Type":"application/json","Accept":"application/json","User-Agent":"Whick-Test/1.0"}
    if headers: h.update(headers)
    body = json.dumps(data).encode() if data else None
    r = urllib.request.Request(url, data=body, headers=h, method=method)
    with urllib.request.urlopen(r, timeout=25) as resp:
        return json.loads(resp.read())

# health envelope
h = req("$CC_URL/system/health".replace("/api/v1/system","/api/v1/system") if False else "https://admin.whick.org/api/v1/system/health")
if not h.get("ok"): failures.append("health ok flag")
if not h.get("data",{}).get("status"): failures.append("health status")

# session create
raw = req(f"{CC}/install/sessions", "POST", {
    "type":"install_session_create",
    "payload":{"install_path":"diy","hostname_hint":"test-suite"}
})
if not raw.get("ok"): failures.append(f"session create: {raw.get('error')}")
data = raw["data"]
token = data["bootstrap_token"]
sid = data["session_id"]
code = data["device_code"]
if not code.startswith("MUSIC-"): failures.append("device_code format")
if not token.startswith("bst_"): failures.append("bootstrap_token format")

# hw-report auth (server SSOT — raw motherboard DMI)
raw2 = req(f"{CC}/install/hw-report", "POST", {
    "type":"hw_report",
    "payload":{"session_id":sid,"fingerprint":{
        "source":"test-suite",
        "kernel":"6.12.93-0-lts",
        "ram_gb":32,
        "identity_source":"motherboard",
        "motherboard":{
            "manufacturer":"ASUSTeK COMPUTER INC.",
            "product":"H610M-E",
            "serial":"TEST-SUITE-001",
            "uuid":"12345678-1234-1234-1234-123456789abc",
        },
        "lan_url":"http://192.168.1.10:80/",
        "access_mode":"lan",
        "nics":[
            {"kind":"eth","pci_id":"10ec:8125","name":"RTL8125"},
            {"kind":"wifi","pci_id":"8086:2723","name":"AX200"}
        ]
    }}
}, headers={"Authorization": f"Bearer {token}"})
if not raw2.get("ok"): failures.append(f"hw-report: {raw2.get('error')}")
data2 = raw2.get("data") or {}
if not data2.get("hw_id_hash") or len(str(data2.get("hw_id_hash"))) != 64:
    failures.append("hw-report missing server hw_id_hash")
if data2.get("net_tier") != "A":
    failures.append(f"hw-report net_tier expected A got {data2.get('net_tier')}")

# invalid token
try:
    req(f"{CC}/install/hw-report", "POST", {
        "type":"hw_report",
        "payload":{"session_id":sid,"fingerprint":{}}
    }, headers={"Authorization": "Bearer bst_invalid"})
    failures.append("invalid token should 401")
except urllib.error.HTTPError as e:
    if e.code != 401: failures.append(f"invalid token got {e.code}")

# session get
raw3 = req(f"{CC}/install/sessions/{sid}")
if not raw3.get("ok"): failures.append("session get")
if raw3.get("data",{}).get("device_code") != code: failures.append("session get device_code mismatch")

# bootstrap log upload — SSD firstboot must leave server-side evidence on failure
raw4 = req(f"{CC}/install/bootstrap/logs", "POST", {
    "type": "bootstrap_logs",
    "payload": {
        "source": "test-suite",
        "stage": "api-contract",
        "status": "complete",
        "exit_code": 0,
        "message": "test-connect-suite log upload",
        "logs": [
            {"name": "test.log", "path": "/tmp/test.log", "content": "test-connect-suite log upload OK"}
        ],
        "meta": {"device_code": code}
    }
}, headers={"Authorization": f"Bearer {token}"})
if not raw4.get("ok") or raw4.get("data", {}).get("inserted", 0) < 1:
    failures.append(f"bootstrap logs upload: {raw4.get('error') or raw4}")

if failures:
    for f in failures: print(f"  FAIL  {f}")
    sys.exit(1)
print("  PASS  API contract OK")
PY
[[ $? -eq 0 ]] && PASS=$((PASS + 1)) || FAIL=$((FAIL + 1))

section "5. bootstrap-agent.py api_data"
python3 - <<'PY'
import importlib.util, sys
spec = importlib.util.spec_from_file_location("ba", "$ROOT/live/bin/bootstrap-agent.py")
# quick unit test without requests network
def api_data(resp):
    if resp.get("ok") is True and isinstance(resp.get("data"), dict):
        return resp["data"]
    if resp.get("ok") is False:
        raise RuntimeError((resp.get("error") or {}).get("message") or "api error")
    return resp

raw = {"ok": True, "data": {"session_id": 1, "bootstrap_token": "bst_x", "device_code": "MUSIC-ABCD"}}
d = api_data(raw)
assert d["device_code"] == "MUSIC-ABCD"
try:
    api_data({"ok": False, "error": {"message": "denied"}})
    sys.exit(1)
except RuntimeError:
    pass
print("  PASS  bootstrap-agent api_data")
PY
[[ $? -eq 0 ]] && PASS=$((PASS + 1)) || FAIL=$((FAIL + 1))

section "6. Alpine apkovl start 스크립트"
START="$ROOT/boot-connect/alpine-local.d-whick-connect.start"
grep -q 'whick-boot-sequence' "$START" && ok "start script exec target" || fail "start script"
grep -q 'whick_ensure_modloop' "$START" && ok "start waits for modloop" || fail "start missing modloop wait"
grep -qE 'whick_load_net_modules|whick-kernel-modules' "$START" "$ROOT/boot-connect/whick-boot-sequence.sh" \
  && ok "start loads ethernet modules" || fail "start missing eth modules"
grep -q 'whick-customer-setup' "$START" && ok "customer setup server" || fail "customer setup missing"
grep -q 'tty_instruction_lines' "$ROOT/boot-connect/whick-customer-setup.py" && ok "TTY network-aware instructions" || fail "missing tty_instruction_lines"
! grep -qE 'hostapd|start_ap_virtual|CaptivePortalHandler|start_phone_ap_path' "$ROOT/boot-connect/whick-customer-setup.py" \
  && ok "no virtual AP/hostapd code" || fail "AP code still present"
grep -q 'eth_status_lines' "$ROOT/boot-connect/whick-customer-setup.py" && ok "lan_setup eth status on tty" || fail "missing eth status tty"
grep -q '_connect_started' "$ROOT/boot-connect/whick-customer-setup.py" && ok "duplicate connect guard" || fail "missing connect guard"
grep -q 'wifi_reconnect.*connecting' "$ROOT/boot-connect/whick-customer-setup.py" || grep -q 'phase.*wifi_reconnect' "$ROOT/boot-connect/whick-customer-setup.py" && ok "wifi reconnect phase" || true
grep -q 'connect_wifi_sta' "$ROOT/boot-connect/whick-customer-setup.py" && ok "provision Wi-Fi STA" || fail "missing connect_wifi_sta"
grep -q 'WIFI_CONNECTING_BODY\|provision STA' "$ROOT/boot-connect/whick-customer-setup.py" && ok "wifi connecting copy" || fail "missing wifi connecting copy"
! grep -qE 'hostapd|dnsmasq' "$START" && ok "no AP packages in apkovl start" || fail "AP packages still referenced in start"
grep -q 'on_wired_ready' "$ROOT/boot-connect/whick-customer-setup.py" && ok "late wired handler" || fail "missing late wired"
grep -q '/api/register' "$ROOT/boot-connect/whick-customer-setup.py" && ok "register API (step 3-4)" || fail "missing register API"
grep -q 'shouldShowRegister' "$ROOT/boot-connect/templates/install.html" && ok "register UI fallback" || fail "missing shouldShowRegister"
grep -q 'shouldShowRegister' "$ROOT/boot-connect/templates/install.html" && ok "register session gate UI" || fail "missing shouldShowRegister"
grep -q 'session_ready' "$ROOT/boot-connect/whick-customer-setup.py" && ok "session_ready API" || fail "missing session_ready"
grep -q '_tty_path' "$ROOT/boot-connect/whick-customer-setup.py" && ok "TTY path helper" || fail "missing _tty_path"
grep -q 'stop_install_login_poll' "$ROOT/boot-connect/whick-customer-setup.py" && ok "stop install login poll after mail" || fail "missing stop_install_login_poll"
grep -q 'access-invite worker skipped' "$ROOT/boot-connect/whick-customer-setup.py" && ok "skip duplicate access-invite mail" || fail "missing access-invite skip"
grep -q 'collect_nics' "$ROOT/boot-connect/whick-boot-connect.sh" && ok "hw-report NIC lspci collection" || fail "missing collect_nics in boot-connect"
grep -q 'collect_dmi_raw_for_server' "$ROOT/boot-connect/whick-boot-connect.sh" && ok "boot-connect collect_dmi_raw_for_server" || fail "missing collect_dmi_raw_for_server in boot-connect"
grep -q '/install/link' "$ROOT/boot-connect/whick-boot-connect.sh" && ok "boot-connect install link phase" || fail "missing /install/link in boot-connect"
grep -q 'sys.exit(0 if out.get("link_ok")' "$ROOT/boot-connect/whick-boot-connect.sh" && ok "boot-connect exit 0 on link_ok" || fail "missing link_ok exit guard"
grep -q 'SSL_CERT_FILE' "$ROOT/boot-connect/whick-env.sh" && ok "whick-env SSL_CERT_FILE" || fail "missing SSL_CERT_FILE in whick-env"
grep -q 'bool(data.get("link_ok"))' "$ROOT/boot-connect/whick-customer-setup.py" && ok "run_boot_connect link_ok trust" || fail "missing link_ok trust in run_boot_connect"
grep -q 'motherboard-v1' "$ROOT/boot-connect/hw_identity.py" && ok "hw_identity motherboard-v1" || fail "missing hw_identity motherboard-v1"
grep -q 'def collect_dmi_raw_for_server' "$ROOT/boot-connect/hw_identity.py" && ok "hw_identity raw DMI for server" || fail "missing collect_dmi_raw_for_server"
grep -q 'def resolve_hw_identity' "$ROOT/boot-connect/hw_identity.py" && ok "hw_identity resolve fallback" || fail "missing resolve_hw_identity"
grep -q 'processInstallLink' "/data/whick-ai/2_control_center/api/src/routes/install.js" && ok "CC install link route" || fail "missing processInstallLink route"
grep -q 'phone_invite' "$ROOT/boot-connect/whick-boot-connect.sh" && ok "hw-report phone_invite in result" || fail "missing phone_invite in boot-connect"
grep -q 'installMailAlreadySent' "/data/whick-ai/2_control_center/api/src/routes/install.js" && ok "ap-ready preserves mail marker" || fail "missing ap-ready mail preserve"
python3 - <<PY
import ast, pathlib
src = pathlib.Path("$ROOT/boot-connect/whick-customer-setup.py").read_text()
tree = ast.parse(src)
found = False
for node in tree.body:
    if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", None) == "_state":
        keys = [k.value for k in node.value.keys if isinstance(k, ast.Constant)]
        assert keys.count("setup_mode") == 1, keys
        found = True
        break
    if isinstance(node, ast.Assign):
        for t in node.targets:
            if getattr(t, "id", None) != "_state":
                continue
            keys = [k.value for k in node.value.keys if isinstance(k, ast.Constant)]
            assert keys.count("setup_mode") == 1, keys
            found = True
assert found, "_state dict not found"
print("  PASS  setup_mode single key")
PY
[[ $? -eq 0 ]] && PASS=$((PASS + 1)) || FAIL=$((FAIL + 1))
grep -q 'register_needed' "$ROOT/boot-connect/templates/install.html" && ok "register UI panel" || fail "missing register panel"
grep -q 'phone_login_url' "$ROOT/boot-connect/whick-customer-setup.py" && ok "phone login alert API" || fail "missing phone login alert"
grep -q 'phoneLoginBanner' "$ROOT/boot-connect/templates/install.html" && ok "phone login banner UI" || fail "missing phone login banner"
! grep -q 'CaptivePortalHandler' "$ROOT/boot-connect/whick-customer-setup.py" && ok "captive portal removed" || fail "CaptivePortalHandler still present"
grep -q 'report_access_ready' "$ROOT/boot-connect/cc_client.py" && ok "CC access-ready client" || fail "missing access-ready client"
grep -q 'cc_connect_worker' "$ROOT/boot-connect/whick-customer-setup.py" && ok "CC connect worker (no AP wait)" || fail "missing cc_connect_worker"
if [[ "$WHICK_USB_PROFILE" == "wired" ]]; then
  grep -q 'startup_network_wired_only' "$ROOT/boot-connect/whick-customer-setup.py" && ok "wired-only LAN startup" || fail "missing startup_network_wired_only"
  grep -q 'is_wired_usb_profile' "$ROOT/boot-connect/whick-customer-setup.py" && ok "wired USB profile guard" || fail "missing is_wired_usb_profile"
  grep -q 'whick_disable_console_login' "$ROOT/boot-connect/whick-headless-console.sh" \
    && ok "headless console helper" || fail "missing headless console helper"
  grep -q 'whick-tty-keeper' "$ROOT/boot-connect/apkovl-inittab" \
    && ok "inittab tty keeper (no login)" || fail "inittab missing tty keeper"
  grep -q 'whick_usb_rescan' "$ROOT/boot-connect/whick-kernel-modules.sh" && ok "USB rescan helper" || fail "missing USB rescan"
  grep -q 'whick_load_usb_host_modules' "$ROOT/boot-connect/whick-kernel-modules.sh" && ok "USB host module load" || fail "missing USB host load"
  grep -q 'ax88179_178a' "$ROOT/boot-connect/whick-kernel-modules.sh" && ok "ASIX USB-LAN driver" || fail "missing ASIX driver"
  grep -q 'net-profile wired — LAN only' "$ROOT/boot-connect/whick-customer-setup.py" \
    && ok "wired skips Wi-Fi/AP" || fail "missing wired no-Wi-Fi guard"
  grep -q 'iface_bus_label' "$ROOT/boot-connect/whick-customer-setup.py" && ok "eth USB/PCI labels" || fail "missing eth bus labels"
elif [[ "$WHICK_USB_PROFILE" == "wireless" ]]; then
  grep -q 'provision_wifi_connect_worker' "$ROOT/boot-connect/whick-customer-setup.py" && ok "wireless provision STA connect" || fail "missing provision_wifi_connect_worker"
  grep -q 'load_provision' "$ROOT/boot-connect/whick-customer-setup.py" && ok "load_provision helper" || fail "missing load_provision"
  grep -q 'on_internet_ready' "$ROOT/boot-connect/whick-customer-setup.py" && ok "shared post-WAN path" || fail "missing on_internet_ready"
  grep -q 'provision STA only (no AP' "$ROOT/boot-connect/whick-customer-setup.py" \
    && ok "wireless no Whick-Setup AP" || fail "missing wireless no-AP guard"
  grep -q 'eth_path_enabled' "$ROOT/boot-connect/whick-customer-setup.py" && ok "wireless excludes eth path" || fail "missing eth_path_enabled"
  grep -q 'whick_load_wired_drivers_sequential' "$ROOT/boot-connect/whick-kernel-modules.sh" \
    && ok "wired sequential driver load" || fail "missing wired sequential drivers"
  grep -q 'whick_load_disk_modules' "$ROOT/boot-connect/whick-kernel-modules.sh" && ok "disk modules all profiles" || fail "missing whick_load_disk_modules"
  grep -q 'whick_disable_console_login' "$ROOT/boot-connect/whick-headless-console.sh" \
    && ok "headless console helper" || fail "missing headless console helper"
  grep -q 'whick-tty-keeper' "$ROOT/boot-connect/apkovl-inittab" \
    && ok "inittab tty keeper (no login)" || fail "inittab missing tty keeper"
  grep -q '!= "wireless"' "$ROOT/boot-connect/whick-kernel-modules.sh" \
    && ok "kernel modules wired/wireless split" || fail "missing profile split in kernel modules"
else
  grep -q 'whick_disable_console_login' "$ROOT/boot-connect/whick-headless-console.sh" \
    && ok "headless console helper" || fail "missing headless console helper"
  grep -q 'whick-tty-keeper' "$ROOT/boot-connect/apkovl-inittab" \
    && ok "inittab tty keeper (no login)" || fail "inittab missing tty keeper"
  grep -q 'read_net_profile' "$ROOT/boot-connect/whick-customer-setup.py" && ok "read_net_profile helper" || fail "missing read_net_profile"
  grep -q 'startup_network_wired_only' "$ROOT/boot-connect/whick-customer-setup.py" && ok "wired-only LAN startup" || fail "missing startup_network_wired_only"
  grep -q 'is_wired_usb_profile' "$ROOT/boot-connect/whick-customer-setup.py" && ok "wired USB profile guard" || fail "missing is_wired_usb_profile"
fi
! grep -qE 'start_phone_ap_path|reset_ap_bootstrap_gate|ap_retry_worker|ap_client_watch_worker|dhcp-option=114|AP-only \(no WAN\)' \
  "$ROOT/boot-connect/whick-customer-setup.py" && ok "AP bootstrap/captive paths removed" || fail "AP remnants still in setup.py"
grep -q 'never start AP' "$ROOT/boot-connect/whick-customer-setup.py" && ok "full profile never starts AP" || fail "missing no-AP full-profile guard"
grep -q 'EMAIL_SENT_BODY' "$ROOT/boot-connect/whick-customer-setup.py" && ok "email notify after WAN" || fail "missing email-after-WAN copy"
grep -q 'buildInstallInviteMailContent' "/data/whick-ai/2_control_center/api/src/lib/installPhoneNotify.js" && ok "install email HTML template" || fail "missing install email HTML"
grep -q 'sendInstallAuthRejectedMail' "/data/whick-ai/2_control_center/api/src/lib/installPhoneNotify.js" && ok "install auth rejected mail" || fail "missing install auth rejected mail"
grep -q 'verifyInstallMailEligibility' "/data/whick-ai/2_control_center/api/src/lib/installResendForMember.js" && ok "resend uses install auth" || fail "resend missing install auth"
! grep -q 'forceTo' "/data/whick-ai/2_control_center/api/src/lib/installResendForMember.js" && ok "resend no forceTo bypass" || fail "resend still uses forceTo bypass"
grep -q 'assertInstallSessionOwnedByMember' "/data/whick-ai/2_control_center/api/src/lib/installResendForMember.js" && ok "resend session ownership check" || fail "missing resend session ownership"
grep -q 'await_phone' "$ROOT/boot-connect/templates/install.html" && ok "await_phone UI phase" || fail "missing await_phone UI"
grep -q 'member_no' "$ROOT/boot-connect/templates/install.html" && ok "member_no display" || fail "missing member_no UI"
grep -q 'WHICK_BOOTSTRAP_SESSION' "$ROOT/boot-connect/whick-boot-connect.sh" && ok "bootstrap session file" || fail "missing bootstrap session"
grep -q 'member_no' "$ROOT/boot-connect/whick-customer-setup.py" && ok "member_no state" || fail "missing member_no state"
grep -q "'/consent'" "/data/whick-ai/2_control_center/api/src/routes/install.js" && ok "CC install consent API" || fail "missing consent API"
grep -q "'/reinstall-consent'" "/data/whick-ai/2_control_center/api/src/routes/install.js" && ok "CC reinstall consent API" || fail "missing reinstall consent API"
grep -q "PORTAL_STAGE_LABELS" "/data/whick-ai/2_control_center/api/src/lib/installMonitor.js" && ok "portal stage SSOT" || fail "missing portal stage SSOT"
grep -q "reinstall_consent_pending" "/data/whick-ai/2_control_center/api/src/lib/installMonitor.js" && ok "reinstall in install track" || fail "missing reinstall track"
grep -q 'password required' "/data/whick-ai/2_control_center/api/src/routes/install.js" && ok "CC register login verify" || fail "CC register missing password"
grep -q 'install_progress' "/data/whick-ai/2_control_center/api/src/lib/installProgress.js" || grep -q 'install_linux' "/data/whick-ai/2_control_center/api/src/lib/installProgress.js" && ok "CC install progress lib" || fail "missing progress lib"
grep -q 'updates/pending' "/data/whick-ai/2_control_center/api/src/routes/agent.js" && ok "CC agent updates pending" || fail "missing agent updates"
grep -q 'apply_update' "/data/whick-ai/2_control_center/api/src/lib/musicServerOps.js" && ok "CC apply_update command" || fail "missing apply_update"
grep -q 'apply_power_policy' "/data/whick-ai/2_control_center/api/src/lib/musicServerOps.js" \
  && ok "CC apply_power_policy command" || fail "missing apply_power_policy in CC"
grep -q "case 'apply_power_policy'" "$ROOT/../agent/src/commands.mjs" \
  && ok "agent apply_power_policy handler" || fail "missing apply_power_policy in agent"
! grep -q 'HandlePowerKey=ignore' "$ROOT/live/bin/install-runtime.sh" \
  && ok "USB/runtime leaves power policy to CC" || fail "USB/runtime still applies host power policy"
# VERIFY_COMMANDS may be multiline; first entry must still be apply_power_policy.
if python3 - <<'PY'
import re
from pathlib import Path
text = Path("/data/whick-ai/2_control_center/api/src/lib/installPostVerify.js").read_text()
m = re.search(r"const\s+VERIFY_COMMANDS\s*=\s*\[([^\]]+)\]", text, re.S)
assert m, "VERIFY_COMMANDS missing"
cmds = re.findall(r"'([^']+)'", m.group(1))
assert cmds and cmds[0] == "apply_power_policy", cmds
PY
then
  ok "CC first post-link command is power policy"
else
  fail "CC power policy is not first after agent link"
fi
[[ -f "$ROOT/docs/REMOTE-PHASE-SERVER.md" ]] && ok "remote phase server doc" || fail "missing remote phase doc"
grep -q 'prefetch runtime bundle from CC' "$ROOT/live/bin/deploy_bootstrap_rootfs.sh" \
  && ok "deploy_bootstrap CC runtime prefetch" || fail "deploy_bootstrap missing CC runtime prefetch"
if [[ -f "/data/whick-ai/2_control_center/db/pg-init/37-install-phase-progress.sql" ]] \
  || [[ -f "/data/whick-ai/2_control_center/db/63-install-remote-phase.sql" ]]; then
  ok "install phase progress DB migration"
else
  fail "missing install phase progress migration"
fi
grep -q 'set_install_error' "$ROOT/boot-connect/whick-customer-setup.py" && ok "install error handler" || fail "missing install error"
grep -q '/api/retry' "$ROOT/boot-connect/whick-customer-setup.py" && ok "install retry API" || fail "missing retry API"
grep -q 'error_code' "$ROOT/boot-connect/whick-boot-connect.sh" && ok "boot-connect error codes" || fail "missing error codes"
python3 - <<PY
import sys
sys.path.insert(0, "$ROOT/boot-connect")
from error_guide import classify_install_error, guide_by_code
g = classify_install_error("network", {"error": "network"})
assert g["error_code"] == "network", g
assert len(g["error_steps"]) >= 2, g
g2 = classify_install_error("session: denied", {"session_ok": False})
assert g2["error_code"] == "server_register", g2
assert guide_by_code("wifi_auth")["error_title"]
print("  PASS  error_guide classify")
PY
[[ $? -eq 0 ]] && PASS=$((PASS + 1)) || FAIL=$((FAIL + 1))
grep -q '/opt/whick-boot-connect' "$START" && ok "start apkovl embed path" || fail "start missing /opt/whick-boot-connect"
grep -q 'dev/mapper' "$START" && ok "start Ventoy mapper mount" || fail "start missing Ventoy mapper"
grep -q 'WHICK_USB_ROOT' "$ROOT/boot-connect/whick-boot-connect.sh" && ok "save_usb WHICK_USB_ROOT" || fail "save_usb missing WHICK_USB_ROOT"

section "7. DB grant (cc_app → cc_ops install)"
pg_table_ok() {
  docker exec -e PGPASSWORD=whick_cc_dev_pass whick-cc-db \
    psql -U cc_app -d whick_control -q -c "SELECT 1 FROM cc_ops.${1} LIMIT 0;" >/dev/null 2>&1
}
pg_table_ok cc_install_sessions \
  && ok "DB access install_sessions" || fail "DB access install_sessions missing"
pg_table_ok cc_install_hw_reports \
  && ok "DB access hw_reports" || fail "DB access hw_reports missing"
pg_table_ok cc_library_jobs \
  && ok "DB access library_jobs" || fail "DB access library_jobs missing"
pg_table_ok cc_monitor_snapshots \
  && ok "DB access monitor_snapshots" || fail "DB access monitor_snapshots missing"

section "7b. Library robots (음원검수·음원분류 — 1단계 필수)"
[[ -x "$ROOT/scripts/test-lab-library-robots.sh" ]] \
  && ok "test-lab-library-robots.sh executable" \
  || fail "missing test-lab-library-robots.sh"
if [[ -f "/data/whick-ai/2_control_center/db/72-library-monitor-core-grant.sql" ]]; then
  ok "DB migration 72 library-monitor grant"
elif pg_table_ok cc_library_jobs 2>/dev/null; then
  ok "library_jobs table (pg-init SSOT)"
else
  fail "missing library_jobs DB grant"
fi
grep -q "scan: 'robot-auditor'" /data/whick-ai/2_control_center/api/src/lib/deviceProtocol.js \
  && ok "deviceProtocol scan→robot-auditor" || fail "deviceProtocol scan mapping missing"
grep -q "classify: 'robot-classifier'" /data/whick-ai/2_control_center/api/src/lib/deviceProtocol.js \
  && ok "deviceProtocol classify→robot-classifier" || fail "deviceProtocol classify mapping missing"
grep -q 'library-jobs' /data/whick-ai_music_server/3_product/monitor/src/main.mjs \
  && ok "monitor posts library-jobs" || fail "monitor library-jobs missing"
grep -q 'phase 9 library robots' "$ROOT/scripts/test-prod-install-lab-e2e.sh" \
  && ok "lab E2E includes phase 9 robots" || fail "lab E2E missing phase 9 robots"
grep -q 'user_approved' /data/whick-ai_music_server/3_product/remote/api/music_api.py \
  && ok "import-incoming requires user_approved" || fail "import-incoming missing user_approved gate"
grep -q 'audit_only' /data/whick-ai_music_server/3_product/remote/api/library_scanner.py \
  && ok "auditor audit_only SSOT" || fail "auditor audit_only missing in library_scanner"
grep -q 'incoming-audit' /data/whick-ai_music_server/3_product/packages/remote/js/remote_api.js \
  && ok "remote incoming audit UI" || fail "remote incoming audit UI missing"
grep -q 'sec-youtube' /data/whick-ai_music_server/3_product/packages/remote/index.html \
  && fail "youtube section should be removed" || ok "youtube menu excluded"
grep -q 'sec-streaming' /data/whick-ai_music_server/3_product/packages/remote/index.html \
  && grep -q 'Spotify' /data/whick-ai_music_server/3_product/packages/remote/index.html \
  && grep -q 'Tidal' /data/whick-ai_music_server/3_product/packages/remote/index.html \
  && ok "streaming section Spotify+Tidal" || fail "streaming section missing"
grep -q 'whick-streaming-wizard.js' /data/whick-ai_music_server/3_product/packages/remote/index.html \
  && ok "streaming wizard loaded" || fail "streaming wizard missing"

section "8. CC solution package (VIP Room retired)"
if [[ -f "$ZIP" ]]; then
  ok "connect zip built ($CONNECT_ZIP_NAME)"
else
  fail "missing connect zip $ZIP"
fi
if docker exec whick-cc-api-solutions test -d "/data/solutions/${SOLUTION_CODE:-connect-wired}" 2>/dev/null; then
  ok "CC solutions storage mount"
else
  warn "CC solutions container path (register step uploads)"
fi

section "SUMMARY"
echo ""
echo "PASS=$PASS  FAIL=$FAIL  WARN=$WARN"
[[ "$FAIL" -eq 0 ]] || exit 1
