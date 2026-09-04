#!/usr/bin/env bash
# Alpine standard ISO → whick alpine-live.iso
# apkovl tarball ISO 루트에 포함 — nlplug-findfs가 *.apkovl.tar.gz 자동 탐색
# (상대경로 apkovl= 는 initramfs에서 깨질 수 있어 사용하지 않음)
# Maker는 이 ISO를 USB에 DD 기록 (Ventoy 미사용)
#
# Alpine mkinitfs 3.11.1: usbdelay= only widens uevent_timeout AFTER bootrepo is
# found without apkovl — it does NOT sleep before the first nlplug-findfs (≈5s).
# We patch initramfs-lts to (1) sleep KOPT_usbdelay before first media scan,
# (2) ignore leftover alpine.apkovl.tar.gz on internal NVMe/HDD (nlplug head -n1
#     otherwise loads /media/nvme… and skips Whick USB overlay → stock login),
# (3) fall back to mounting ISO9660/USB volumes for alpine.apkovl.tar.gz.
set -euo pipefail

SRC="${1:?source iso}"
DST="${2:?output iso}"
APKOVL="${3:-}"
EXTRA="${WHICK_ALPINE_BOOT_EXTRA:- console=tty0 usbdelay=30}"

run_patch() {
  local src_base dst_base apkovl_base
  src_base="$(basename "$SRC")"
  dst_base="$(basename "$DST")"
  apkovl_base=""
  if [[ -n "$APKOVL" ]]; then
    apkovl_base="$(basename "$APKOVL")"
  fi

  docker run --rm \
    -v "$(dirname "$SRC"):/in:ro" \
    -v "$(dirname "$DST"):/out" \
    ${APKOVL:+-v "$(dirname "$APKOVL"):/apkin:ro"} \
    -e "WHICK_EXTRA=$EXTRA" \
    -e "APKOVL_FILE=${apkovl_base}" \
    -e "SRC_BASE=${src_base}" \
    -e "DST_BASE=${dst_base}" \
    debian:bookworm-slim bash -c "$(cat <<'DOCKER_SCRIPT'
set -e
apt-get update -qq && apt-get install -qq -y libarchive-tools xorriso python3 syslinux-common isolinux fdisk gzip cpio binutils >/dev/null
SRC="/in/${SRC_BASE}"
DST="/out/${DST_BASE}"
WORK=/tmp/apk
rm -rf "$WORK" && mkdir -p "$WORK/src"
bsdtar -xf "$SRC" -C "$WORK/src"
if [[ -n "${APKOVL_FILE}" ]]; then
  cp "/apkin/${APKOVL_FILE}" "$WORK/src/alpine.apkovl.tar.gz"
  test -s "$WORK/src/alpine.apkovl.tar.gz"
  echo "embedded alpine.apkovl.tar.gz in ISO root"
fi
# Preserve source volume label (EFI GRUB search --label must match)
VOL_ID="$(xorriso -indev "$SRC" -pvd_info 2>/dev/null | awk -F': ' '/^Volume Id[[:space:]]*:/{print $2; exit}' | sed 's/[[:space:]]*$//')"
if [[ -z "$VOL_ID" ]]; then
  VOL_ID="alpine-std 3.21.7 x86_64"
fi
echo "volume id: [$VOL_ID]"
# isohybrid MBR prefix (USB DD / BIOS boot) — from syslinux package
ISOHDPFX=""
for c in /usr/lib/ISOLINUX/isohdpfx.bin /usr/lib/syslinux/isohdpfx.bin /usr/share/syslinux/isohdpfx.bin; do
  if [[ -f "$c" ]]; then ISOHDPFX="$c"; break; fi
done
if [[ -z "$ISOHDPFX" ]]; then
  echo "FATAL: isohdpfx.bin not found (syslinux-common)" >&2
  exit 1
fi
echo "isohybrid mbr: $ISOHDPFX"

# --- A) Patch grub/syslinux cmdline ---
python3 - <<'PY'
import re, os
from pathlib import Path
extra = os.environ["WHICK_EXTRA"].strip()
if not extra:
    raise SystemExit("WHICK_EXTRA empty")
root = Path("/tmp/apk/src")
need_mods = ["loop", "squashfs", "sd-mod", "usb-storage", "vfat", "isofs"]

def patch_text(text: str, rel: str) -> str:
    text = re.sub(r"\sapkovl=\S+", "", text)
    text = re.sub(r"\susbdelay=\S+", "", text)
    text = re.sub(r"\squiet\b", "", text)
    text = re.sub(r"\sconsole=\S+", "", text)

    def _ensure_mods(m):
        mods = [x for x in m.group(1).split(",") if x]
        for need in need_mods:
            if need not in mods:
                mods.append(need)
        return "modules=" + ",".join(mods)

    text2, n = re.subn(r"modules=([^\s]+)", _ensure_mods, text, count=1)
    if n != 1:
        raise SystemExit(f"modules= not found once in {rel}")
    text = text2

    def _append_extra(m):
        return m.group(0).rstrip() + " " + extra

    text = re.sub(
        r"(^[^\n]*modules=\S+[^\n]*)",
        _append_extra,
        text,
        count=1,
        flags=re.M,
    )
    text = "\n".join(re.sub(r"[ \t]{2,}", " ", ln).rstrip() for ln in text.splitlines()) + "\n"

    if re.search(r"\bquiet\b", text):
        raise SystemExit(f"patch failed (quiet must be removed): {rel}")
    if "apkovl=" in text:
        raise SystemExit(f"patch failed (apkovl= must be omitted for nlplug auto-find): {rel}")
    if "usbdelay=" not in text:
        raise SystemExit(f"patch failed (usbdelay): {rel}")
    if "isofs" not in text:
        raise SystemExit(f"patch failed (isofs module required): {rel}")
    if "console=tty0" not in text:
        raise SystemExit(f"patch failed (console=tty0): {rel}")
    if "vfat" not in text:
        raise SystemExit(f"patch failed (vfat module required): {rel}")
    return text

for rel in ("boot/grub/grub.cfg", "boot/syslinux/syslinux.cfg"):
    p = root / rel
    if not p.is_file():
        raise SystemExit(f"missing {rel}")
    p.write_text(patch_text(p.read_text(), rel))
    print("patched", rel)
PY

# --- B) Patch initramfs-lts: usbdelay sleep + apkovl ISO fallback ---
INITRD="$WORK/src/boot/initramfs-lts"
test -f "$INITRD"
IRM="$WORK/initrd-root"
rm -rf "$IRM" && mkdir -p "$IRM"
( cd "$IRM" && gzip -dc "$INITRD" | cpio -idm )
test -f "$IRM/init"
python3 - <<'PY'
from pathlib import Path
import re

init_path = Path("/tmp/apk/initrd-root/init")
text = init_path.read_text()

SLEEP_MARK = "Whick: waiting"
PREFER_MARK = "Whick: ignoring internal-disk apkovl"
FALLBACK_MARK = "Whick: found apkovl"

SLEEP_BLOCK = (
    "# Whick: honor usbdelay as real sleep before first media scan (Alpine 3.11.1 does not)\n"
    'if [ -n "$KOPT_usbdelay" ]; then\n'
    '\techo "Whick: waiting ${KOPT_usbdelay}s for USB media..."\n'
    '\tsleep "$KOPT_usbdelay"\n'
    "fi\n"
)
# After nlplug sets ovl=$(head -n1 apkovls), drop internal-disk leftovers and
# re-pick first non-NVMe/HDD candidate (USB / optical / virtio).
PREFER_BLOCK = (
    "# Whick: prefer USB/ISO apkovl — never leftover on internal NVMe/HDD\n"
    'case "$ovl" in\n'
    "\t/media/nvme*|/media/hd*)\n"
    '\t\techo "Whick: ignoring internal-disk apkovl $ovl"\n'
    "\t\tovl=\n"
    "\t\t;;\n"
    "esac\n"
    'if [ -e "$ROOT"/tmp/apkovls ]; then\n'
    "\t_whick_pick=\n"
    '\twhile read -r _whick_cand; do\n'
    '\t\tcase "$_whick_cand" in\n'
    "\t\t\t/media/nvme*|/media/hd*|\"\") continue ;;\n"
    '\t\t\t*) _whick_pick="$_whick_cand"; break ;;\n'
    "\t\tesac\n"
    '\tdone < "$ROOT"/tmp/apkovls\n'
    '\tif [ -n "$_whick_pick" ]; then\n'
    '\t\tovl="$_whick_pick"\n'
    '\t\techo "Whick: using boot-media apkovl $ovl"\n'
    "\tfi\n"
    "\tunset _whick_pick _whick_cand\n"
    "fi\n"
)
FALLBACK_BLOCK = (
    "# Whick: fallback — mount ISO9660/USB volumes for alpine.apkovl.tar.gz (never NVMe)\n"
    'if [ -z "$ovl" ] || [ ! -f "$ovl" ]; then\n'
    "\tmkdir -p /media/whick-ovl\n"
    "\tfor _dev in /dev/disk/by-label/* /dev/sr0 /dev/sr1 /dev/vd* /dev/sd*[0-9] /dev/sd[a-z]; do\n"
    '\t\t[ -e "$_dev" ] || continue\n'
    '\t\tcase "$_dev" in\n'
    "\t\t\t*nvme*) continue ;;\n"
    "\t\tesac\n"
    '\t\tumount /media/whick-ovl 2>/dev/null || true\n'
    '\t\tmount -t iso9660 -o ro "$_dev" /media/whick-ovl 2>/dev/null || \\\n'
    '\t\t\tmount -o ro "$_dev" /media/whick-ovl 2>/dev/null || continue\n'
    "\t\tif [ -f /media/whick-ovl/alpine.apkovl.tar.gz ]; then\n"
    "\t\t\tovl=/media/whick-ovl/alpine.apkovl.tar.gz\n"
    '\t\t\techo "Whick: found apkovl at $ovl"\n'
    "\t\t\tbreak\n"
    "\t\tfi\n"
    "\t\tumount /media/whick-ovl 2>/dev/null || true\n"
    "\tdone\n"
    "fi\n"
)

# Idempotent: strip prior Whick blocks if re-patching
text = re.sub(
    r"\n# Whick: honor usbdelay as real sleep before first media scan \(Alpine 3\.11\.1 does not\)\n"
    r"if \[ -n \"\$KOPT_usbdelay\" \]; then\n"
    r".*?\nfi\n",
    "\n",
    text,
    count=1,
    flags=re.S,
)
text = re.sub(
    r"\n# Whick: prefer USB/ISO apkovl — never leftover on internal NVMe/HDD\n"
    r"case \"\$ovl\" in\n"
    r".*?\nfi\n",
    "\n",
    text,
    count=1,
    flags=re.S,
)
text = re.sub(
    r"\n# Whick: fallback — mount ISO9660(?:/USB)? volumes (?:and look for|for) alpine\.apkovl\.tar\.gz[^\n]*\n"
    r"if \[ -z \"\$ovl\" \] \|\| \[ ! -f \"\$ovl\" \]; then\n"
    r".*?\nfi\n",
    "\n",
    text,
    count=1,
    flags=re.S,
)

anchor = "# locate boot media and mount it"
idx = text.find(anchor)
if idx < 0:
    raise SystemExit("init: missing '# locate boot media and mount it'")
after = text[idx:idx + 400]
if "nlplug-findfs" not in after or "apkovls" not in after:
    raise SystemExit("init: expected nlplug-findfs -a apkovls after locate-boot-media anchor")
text = text[:idx] + SLEEP_BLOCK + "\n" + text[idx:]

load_anchor = "# load apkovl or set up a minimal system"
lidx = text.find(load_anchor)
if lidx < 0:
    raise SystemExit("init: missing '# load apkovl or set up a minimal system'")
pre = text[:lidx]
if "ovl=$(head" not in pre:
    raise SystemExit("init: ovl assignment not found before load-apkovl")
text = text[:lidx] + PREFER_BLOCK + "\n" + FALLBACK_BLOCK + "\n" + text[lidx:]

if SLEEP_MARK not in text or PREFER_MARK not in text or FALLBACK_MARK not in text:
    raise SystemExit("init: Whick markers missing after patch")
init_path.write_text(text)
print("patched initramfs init (usbdelay sleep + prefer USB apkovl + ISO fallback)")
PY
( cd "$IRM" && find . | cpio -o -H newc 2>/dev/null | gzip -9 > "$INITRD" )
test -s "$INITRD"
echo "repacked boot/initramfs-lts ($(wc -c < "$INITRD") bytes)"

# --- C) xorriso remaster (isohybrid-mbr + GPT basdat, stock Alpine style) ---
cd "$WORK/src"
xorriso -as mkisofs \
  -V "$VOL_ID" \
  -r -J -joliet-long -l -iso-level 3 \
  -b boot/syslinux/isolinux.bin -c boot/syslinux/boot.cat \
  -no-emul-boot -boot-load-size 4 -boot-info-table \
  -isohybrid-mbr "$ISOHDPFX" \
  -eltorito-alt-boot -e boot/grub/efi.img -no-emul-boot \
  -isohybrid-gpt-basdat \
  -o "$DST" .

# --- D) Verification ---
bsdtar -tf "$DST" | grep -qx alpine.apkovl.tar.gz
GRUB="$(bsdtar -xOf "$DST" boot/grub/grub.cfg)"
echo "$GRUB" | grep -q "usbdelay="
echo "$GRUB" | grep -q "isofs"
echo "$GRUB" | grep -q "console=tty0"
echo "$GRUB" | grep -q "vfat"
! echo "$GRUB" | grep -qE '(^|[[:space:]])quiet([[:space:]]|$)'
! echo "$GRUB" | grep -q "apkovl="
SYSL="$(bsdtar -xOf "$DST" boot/syslinux/syslinux.cfg)"
echo "$SYSL" | grep -q "usbdelay="
echo "$SYSL" | grep -q "isofs"
echo "$SYSL" | grep -q "console=tty0"
echo "$SYSL" | grep -q "vfat"
! echo "$SYSL" | grep -qE '(^|[[:space:]])quiet([[:space:]]|$)'
! echo "$SYSL" | grep -q "apkovl="
bsdtar -xOf "$DST" boot/initramfs-lts > /tmp/out-initrd
gzip -dc /tmp/out-initrd | strings | grep -q "Whick: waiting"
gzip -dc /tmp/out-initrd | strings | grep -q "Whick: ignoring internal-disk apkovl"
gzip -dc /tmp/out-initrd | strings | grep -q "Whick: found apkovl"
echo "initramfs Whick markers OK"
python3 - <<'PY'
from pathlib import Path
import os
b = Path("/out/" + os.environ["DST_BASE"]).read_bytes()[:512]
assert len(b) == 512, len(b)
assert b[510] == 0x55 and b[511] == 0xAA, "missing isohybrid MBR signature 55AA"
print("isohybrid MBR 55AA OK")
PY
OUT_VOL="$(xorriso -indev "$DST" -pvd_info 2>/dev/null | awk -F': ' '/^Volume Id[[:space:]]*:/{print $2; exit}' | sed 's/[[:space:]]*$//')"
echo "out volume id: [$OUT_VOL]"
test "$OUT_VOL" = "$VOL_ID"
echo "ISO verify OK (hybrid + label + initramfs Whick)"
DOCKER_SCRIPT
)"
}

[[ -f "$SRC" ]] || { echo "missing source: $SRC" >&2; exit 1; }
[[ -n "$APKOVL" ]] || { echo "missing apkovl: pass alpine.apkovl.tar.gz as 3rd arg" >&2; exit 1; }
[[ -f "$APKOVL" ]] || { echo "apkovl not found: $APKOVL" >&2; exit 1; }
mkdir -p "$(dirname "$DST")"
run_patch
echo "OK patched ISO → $DST"
