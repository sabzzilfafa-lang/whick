#!/usr/bin/env bash
# VIP 맞춤 USB — Live ISO 에 provision/net-profile 주입 후 hybrid remaster
# (단순 xorriso -map 은 GPT/hybrid 꼬임 → extract + as_mkisofs SSOT)
#
# Usage:
#   ./inject-provision-into-live-iso.sh --iso whick-os-live-wireless.iso --boot-dir ./whick-boot-connect
#   ./inject-provision-into-live-iso.sh --iso in.iso --boot-dir ./whick-boot-connect --out out.iso
set -euo pipefail

ISO_IN=""
BOOT_DIR=""
ISO_OUT=""
SETUP_PY="${WHICK_INJECT_SETUP_PY:-}"
BOOT_CONNECT_SH="${WHICK_INJECT_BOOT_CONNECT_SH:-}"

usage() {
  cat <<EOF
Usage: $(basename "$0") --iso ISO --boot-dir DIR [--out ISO] [--setup-py FILE]

  Injects net-profile / provision.json / whick-bootstrap-session.json into
  /whick-os/opt/whick/boot-connect and /casper/whick-os/... then remasters
  hybrid GPT (same recipe as build-whick-os-live.sh).
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --iso) ISO_IN="${2:-}"; shift 2 ;;
    --boot-dir) BOOT_DIR="${2:-}"; shift 2 ;;
    --out) ISO_OUT="${2:-}"; shift 2 ;;
    --setup-py) SETUP_PY="${2:-}"; shift 2 ;;
    --boot-connect-sh) BOOT_CONNECT_SH="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown: $1" >&2; usage; exit 1 ;;
  esac
done

[[ -n "$ISO_IN" && -f "$ISO_IN" ]] || { echo "ERROR: --iso required" >&2; exit 1; }
[[ -n "$BOOT_DIR" && -d "$BOOT_DIR" ]] || { echo "ERROR: --boot-dir required" >&2; exit 1; }
command -v xorriso >/dev/null || { echo "ERROR: xorriso required" >&2; exit 1; }
command -v sgdisk >/dev/null || { echo "ERROR: sgdisk required" >&2; exit 1; }

ISO_IN="$(readlink -f "$ISO_IN")"
BOOT_DIR="$(readlink -f "$BOOT_DIR")"
if [[ -z "$ISO_OUT" ]]; then
  ISO_OUT="$ISO_IN"
fi
ISO_OUT="$(readlink -f "$ISO_OUT" 2>/dev/null || echo "$ISO_OUT")"

WORK="${WHICK_ISO_INJECT_WORK:-/mnt/ssd2/scratch/runs/iso-provision-inject-$$}"
mkdir -p "$WORK"
cleanup() { rm -rf "$WORK"; }
trap cleanup EXIT

TREE="$WORK/tree"
BOOTBITS="$WORK/bootbits"
TMP_OUT="$WORK/out.iso"
mkdir -p "$TREE" "$BOOTBITS"

echo "==> extract $ISO_IN"
xorriso -osirrox on -indev "$ISO_IN" -extract / "$TREE"
chmod -R u+w "$TREE"

inject_into() {
  local dest="$1"
  mkdir -p "$dest"
  for f in net-profile provision.json whick-bootstrap-session.json; do
    if [[ -f "$BOOT_DIR/$f" ]]; then
      cp -f "$BOOT_DIR/$f" "$dest/$f"
      [[ "$f" == "net-profile" ]] || chmod 600 "$dest/$f" 2>/dev/null || true
      echo "  + $dest/$f"
    fi
  done
  if [[ -n "$SETUP_PY" && -f "$SETUP_PY" ]]; then
    cp -f "$SETUP_PY" "$dest/whick-customer-setup.py"
    echo "  + $dest/whick-customer-setup.py (override)"
  fi
  # Ubuntu Live 베이스 ISO 가 옛 boot-connect 를 들고 있어도 맞춤 빌드마다 최신 주입
  local bc_sh="${BOOT_CONNECT_SH:-}"
  if [[ -z "$bc_sh" && -f "$BOOT_DIR/whick-boot-connect.sh" ]]; then
    bc_sh="$BOOT_DIR/whick-boot-connect.sh"
  fi
  if [[ -z "$bc_sh" ]]; then
    for cand in \
      /data/whick-ai_music_server/3_product/uab/boot-connect/whick-boot-connect.sh \
      /mnt/ssd2/dev/whick-ai_music_server/3_product/uab/boot-connect/whick-boot-connect.sh
    do
      [[ -f "$cand" ]] && bc_sh="$cand" && break
    done
  fi
  if [[ -n "$bc_sh" && -f "$bc_sh" ]]; then
    cp -f "$bc_sh" "$dest/whick-boot-connect.sh"
    chmod 755 "$dest/whick-boot-connect.sh"
    echo "  + $dest/whick-boot-connect.sh (override)"
  fi
}

[[ -d "$TREE/whick-os/opt/whick/boot-connect" ]] || {
  echo "ERROR: ISO missing /whick-os/opt/whick/boot-connect" >&2
  exit 1
}

echo "==> inject provision files"
inject_into "$TREE/whick-os/opt/whick/boot-connect"
if [[ -d "$TREE/casper/whick-os/opt/whick/boot-connect" ]]; then
  inject_into "$TREE/casper/whick-os/opt/whick/boot-connect"
fi

# 베이스 테스트 ISO 가 whick-env.sh 에 127.0.0.1:18095 를 export 로 박아 둠 →
# live-debug.env 를 고쳐도 boot-connect 가 whick-env.sh 를 나중에 source 하며 덮어씀.
pin_boot_connect_cc_url() {
  local dest="$1"
  local envf="$dest/whick-env.sh"
  [[ -f "$envf" ]] || return 0
  local device_cc="${WHICK_DEVICE_CC_API_URL:-}"
  if [[ -z "$device_cc" ]]; then
    local pub="${WHICK_CC_PUBLIC_URL:-}"
    pub="${pub%/}"
    if [[ -n "$pub" && "$pub" != *127.0.0.1* && "$pub" != *localhost* ]]; then
      if [[ "$pub" == */api/v1 ]]; then device_cc="$pub"; else device_cc="$pub/api/v1"; fi
    fi
  fi
  device_cc="${device_cc%/}"
  [[ -n "$device_cc" ]] || {
    echo "ERROR: cannot pin whick-env.sh CC URL (WHICK_DEVICE_CC_API_URL unset)" >&2
    return 2
  }
  if [[ "$device_cc" == *127.0.0.1* || "$device_cc" == *localhost* ]]; then
    echo "ERROR: refusing localhost CC URL for device USB: $device_cc" >&2
    return 2
  fi
  python3 - "$envf" "$device_cc" <<'PY'
import pathlib, shlex, sys
path, cc = pathlib.Path(sys.argv[1]), sys.argv[2].rstrip("/")
keys = ("WHICK_CC_API_URL", "WHICK_CANONICAL_CC_API_URL")
lines = [
    ln for ln in path.read_text(encoding="utf-8").splitlines()
    if not any(ln.startswith(f"export {k}=") or ln.startswith(f"{k}=") for k in keys)
]
for k in keys:
    lines.append(f"export {k}={shlex.quote(cc)}")
# test-admin 등 공개 HTTPS 는 tunnel 이 아니어도 허용
if not any(ln.startswith("export WHICK_ALLOW_NON_TUNNEL_CC=") for ln in lines):
    lines.append("export WHICK_ALLOW_NON_TUNNEL_CC=1")
path.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"  + {path} CC_API_URL={cc}")
PY
}
pin_boot_connect_cc_url "$TREE/whick-os/opt/whick/boot-connect"
if [[ -d "$TREE/casper/whick-os/opt/whick/boot-connect" ]]; then
  pin_boot_connect_cc_url "$TREE/casper/whick-os/opt/whick/boot-connect"
fi

# ISO 권한 600 이면 일부 부팅 경로에서 못 읽는 경우 있음 → 644
for f in \
  "$TREE/whick-os/opt/whick/boot-connect/provision.json" \
  "$TREE/casper/whick-os/opt/whick/boot-connect/provision.json" \
  "$TREE/whick-os/opt/whick/boot-connect/whick-bootstrap-session.json" \
  "$TREE/casper/whick-os/opt/whick/boot-connect/whick-bootstrap-session.json"
do
  [[ -f "$f" ]] && chmod 644 "$f" || true
done

# etc/whick — net-profile + provision + live-debug.env 에 SSID 핀 (start.sh 가 source)
pin_etc_whick() {
  local etc="$1"
  [[ -d "$etc" ]] || return 0
  if [[ -f "$BOOT_DIR/net-profile" ]]; then
    cp -f "$BOOT_DIR/net-profile" "$etc/net-profile"
    echo "  + ${etc#*$TREE}/net-profile"
  fi
  if [[ -f "$BOOT_DIR/provision.json" ]]; then
    cp -f "$BOOT_DIR/provision.json" "$etc/provision.json"
    chmod 644 "$etc/provision.json"
    echo "  + ${etc#*$TREE}/provision.json"
  fi
  if [[ -f "$BOOT_DIR/provision.json" && -f "$etc/live-debug.env" ]]; then
    python3 - "$BOOT_DIR/provision.json" "$etc/live-debug.env" <<'PY'
import json, os, pathlib, re, shlex, sys
from datetime import datetime, timezone, timedelta
prov = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
env_path = pathlib.Path(sys.argv[2])
ssid = str(prov.get("wifi_ssid") or "").strip()
pwd = str(prov.get("wifi_password") or "")
pid = str(prov.get("provision_id") or "x").strip()
kst = timezone(timedelta(hours=9))
stamp = datetime.now(kst).strftime("%m%d%H%M")
build = f"prov{pid}-{stamp}"
# 미니PC가 붙을 공개 CC API (127.0.0.1:18095 는 서버 로컬 전용 — Live USB에 넣으면 server_unreachable)
device_cc = (
    os.environ.get("WHICK_DEVICE_CC_API_URL")
    or os.environ.get("WHICK_CONNECT_DEVICE_CC_API_URL")
    or ""
).strip().rstrip("/")
if not device_cc:
    pub = (os.environ.get("WHICK_CC_PUBLIC_URL") or "").strip().rstrip("/")
    if pub and "127.0.0.1" not in pub and "localhost" not in pub:
        device_cc = pub if pub.endswith("/api/v1") else f"{pub}/api/v1"
lines = [
    ln for ln in env_path.read_text(encoding="utf-8").splitlines()
    if not ln.startswith("WHICK_PROVISION_WIFI_SSID=")
    and not ln.startswith("WHICK_PROVISION_WIFI_PASSWORD=")
    and not ln.startswith("WHICK_CONNECT_BUILD=")
]
if device_cc:
    out = []
    for ln in lines:
        if ln.startswith("WHICK_CC_API_URL=") or ln.startswith("WHICK_CANONICAL_CC_API_URL="):
            continue
        out.append(ln)
    out.append(f"WHICK_CC_API_URL={device_cc}")
    out.append(f"WHICK_CANONICAL_CC_API_URL={device_cc}")
    lines = out
    print(f"  + live-debug.env WHICK_CC_API_URL={device_cc}")
elif any("127.0.0.1" in ln or "localhost" in ln for ln in lines if ln.startswith("WHICK_CC_API_URL=")):
    print("ERROR: live-debug.env has localhost CC URL and WHICK_DEVICE_CC_API_URL unset", file=sys.stderr)
    sys.exit(2)
if ssid:
    lines.append(f"WHICK_PROVISION_WIFI_SSID={shlex.quote(ssid)}")
    lines.append(f"WHICK_PROVISION_WIFI_PASSWORD={shlex.quote(pwd)}")
    lines.append(f"WHICK_CONNECT_BUILD={build}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"  + live-debug.env WHICK_PROVISION_WIFI_SSID={ssid!r} BUILD={build}")
else:
    print("  WARN: provision.json has empty wifi_ssid — skip env pin", file=sys.stderr)
    sys.exit(1)
PY
  fi
}
pin_etc_whick "$TREE/whick-os/etc/whick"
pin_etc_whick "$TREE/casper/whick-os/etc/whick"

# Live 부팅 FAILED ssh* 스팸 — 맞춤 USB remaster 때도 GRUB cmdline 에 mask 강제
# (베이스 ISO 가 옛 빌드여도 새 zip 에 반영)
patch_live_ssh_masks() {
  local grub="$TREE/boot/grub/grub.cfg"
  [[ -f "$grub" ]] || return 0
  python3 - "$grub" <<'PY'
from pathlib import Path
import sys
p = Path(sys.argv[1])
text = p.read_text(encoding="utf-8", errors="replace")
masks = [
    "systemd.mask=ssh.service",
    "systemd.mask=ssh.socket",
    "systemd.mask=sshd.service",
    "systemd.mask=sshd.socket",
]
changed = False
out = []
for ln in text.splitlines():
    if ln.strip().startswith("linux ") and "casper/vmlinuz" in ln:
        for m in masks:
            if m not in ln:
                # insert before --- or at end of linux line args
                if " --- " in ln:
                    ln = ln.replace(" --- ", f" {m} --- ", 1)
                else:
                    ln = ln.rstrip() + " " + m
                changed = True
    out.append(ln)
if changed:
    p.write_text("\n".join(out) + "\n", encoding="utf-8")
    print("  + grub.cfg systemd.mask=ssh*|sshd*")
else:
    print("  · grub.cfg already has ssh masks (or no linux lines)")
PY
}
echo "==> patch Live ssh FAILED masks into GRUB"
patch_live_ssh_masks

PROFILE="$(tr -d '\r\n' <"$BOOT_DIR/net-profile" 2>/dev/null || echo wireless)"
case "$PROFILE" in wired|wireless) ;; *) PROFILE=wireless ;; esac
VOLID="WHICK_OS_${PROFILE}"

echo "==> extract EFI appended partition from source ISO"
efi_start="$(sgdisk -i 2 "$ISO_IN" | awk -F: '/First sector/{match($2,/[0-9]+/); print substr($2,RSTART,RLENGTH); exit}')"
efi_end="$(sgdisk -i 2 "$ISO_IN" | awk -F: '/Last sector/{match($2,/[0-9]+/); print substr($2,RSTART,RLENGTH); exit}')"
[[ -n "$efi_start" && -n "$efi_end" ]] || { echo "ERROR: cannot read EFI partition" >&2; exit 1; }
efi_count=$((efi_end - efi_start + 1))
dd if="$ISO_IN" of="$BOOTBITS/efi.img" bs=512 skip="$efi_start" count="$efi_count" status=none
ls -lh "$BOOTBITS/efi.img"

echo "==> as_mkisofs remaster volid=$VOLID"
rm -f "$TMP_OUT"
xorriso -as mkisofs \
  -r -J -joliet-long \
  -V "$VOLID" \
  -o "$TMP_OUT" \
  --grub2-mbr "--interval:local_fs:0s-15s:zero_mbrpt,zero_gpt:${ISO_IN}" \
  --protective-msdos-label \
  -partition_cyl_align off \
  -partition_offset 16 \
  --mbr-force-bootable \
  -append_partition 2 28732ac11ff8d211ba4b00a0c93ec93b "$BOOTBITS/efi.img" \
  -appended_part_as_gpt \
  -iso_mbr_part_type a2a0d0ebe5b9334487c068b6b72699c7 \
  -c '/boot.catalog' \
  -b '/boot/grub/i386-pc/eltorito.img' \
  -no-emul-boot \
  -boot-load-size 4 \
  -boot-info-table \
  --grub2-boot-info \
  -eltorito-alt-boot \
  -e '--interval:appended_partition_2:all::' \
  -no-emul-boot \
  -boot-load-size "$efi_count" \
  "$TREE"

python3 - "$TMP_OUT" "$efi_count" <<'PY'
import sys
from pathlib import Path
p = Path(sys.argv[1])
efi_count = int(sys.argv[2])
size = p.stat().st_size
secs = size // 512
b = p.read_bytes()
assert b[510] == 0x55 and b[511] == 0xAA, "MBR 55AA missing"
gpt = b[512:1024]
assert gpt[0:8] == b"EFI PART", "GPT header missing"
backup = int.from_bytes(gpt[32:40], "little")
assert backup == secs - 1, f"backup GPT not at EOF (backup={backup} last={secs-1})"
print("hybrid_ok size_mb", round(size / 1024 / 1024, 1), "efi_sectors", efi_count)
PY

mkdir -p "$(dirname "$ISO_OUT")"
mv -f "$TMP_OUT" "$ISO_OUT"
echo "OK  $ISO_OUT"
