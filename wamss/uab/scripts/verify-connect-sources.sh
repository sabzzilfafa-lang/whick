#!/usr/bin/env bash
# connect-usb 소스 정적 검증 — 빌드 전 필수 (ISO-DD Maker · apkovl 등)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PS1="$ROOT/windows/Whick-USB-Maker.ps1"
BAT="$ROOT/windows/make-usb.bat"
FAIL=0

die() { echo "  FAIL  $*" >&2; FAIL=$((FAIL + 1)); }
ok()  { echo "  PASS  $*"; }

section() { echo ""; echo "== $* =="; }

section "소스 파일"
REQUIRED=(
  "$BAT"
  "$PS1"
  "$ROOT/boot-connect/whick-boot-connect.sh"
  "$ROOT/boot-connect/whick-boot-sequence.sh"
  "$ROOT/boot-connect/whick-customer-setup.py"
  "$ROOT/boot-connect/hw_identity.py"
  "$ROOT/boot-connect/alpine-local.d-whick-connect.start"
  "$ROOT/boot-connect/alpine-init.d-whick-modloop"
  "$ROOT/boot-connect/alpine-init.d-whick-no-login"
  "$ROOT/boot-connect/whick-headless-console.sh"
  "$ROOT/boot-connect/whick-tty-keeper.sh"
  "$ROOT/boot-connect/apkovl-inittab"
  "$ROOT/docs/USB-고객안내.txt"
  "$ROOT/docs/USB-고객안내-유선.txt"
  "$ROOT/docs/USB-고객안내-무선.txt"
  "$ROOT/docs/USB-저작권-배포안내.txt"
  "$ROOT/scripts/patch-alpine-live-iso.sh"
)
for f in "${REQUIRED[@]}"; do
  [[ -f "$f" ]] && ok "$(basename "$f")" || die "missing $f"
done

section "Whick-USB-Maker.ps1 (ISO → USB DD)"
grep -q 'Request-WhickAdmin' "$PS1" \
  && ok "admin elevation (hidden)" || die "PS1 missing Request-WhickAdmin"
grep -q 'Write-WhickIsoToPhysicalDrive' "$PS1" \
  && ok "ISO DD writer" || die "PS1 missing Write-WhickIsoToPhysicalDrive"
grep -q 'PhysicalDrive' "$PS1" \
  && ok "PhysicalDrive raw write" || die "PS1 missing PhysicalDrive"
! grep -q 'Invoke-VentoyCli' "$PS1" \
  && ok "no Ventoy CLI (ISO-DD path)" || die "PS1 must not call Ventoy"
! grep -q 'ventoy-portable' "$PS1" \
  && ok "no ventoy-portable dependency" || die "PS1 must not require ventoy-portable"
grep -q 'alpine-live.iso' "$PS1" \
  && ok "requires alpine-live.iso" || die "PS1 missing alpine-live.iso check"

section "make-usb.bat"
grep -q 'WindowStyle Hidden' "$BAT" \
  && ok "BAT hidden PowerShell launch" || die "BAT missing WindowStyle Hidden"

section "ISO patch / apkovl"
grep -q 'usbdelay=' "$ROOT/scripts/patch-alpine-live-iso.sh" \
  && ok "ISO patch sets usbdelay" || die "patch-alpine-live-iso missing usbdelay"
grep -q 'apkovl= must be omitted\|apkovl=\S+' "$ROOT/scripts/patch-alpine-live-iso.sh" \
  && ok "ISO patch handles apkovl= policy" || die "patch script apkovl policy unclear"
grep -q 'console=tty0' "$ROOT/scripts/patch-alpine-live-iso.sh" \
  && ok "ISO patch sets console=tty0" || die "patch-alpine-live-iso missing console=tty0"
grep -q 'Whick: waiting' "$ROOT/scripts/patch-alpine-live-iso.sh" \
  && ok "ISO patch injects initramfs usbdelay sleep" || die "patch missing Whick usbdelay sleep"
grep -q 'Whick: ignoring internal-disk apkovl' "$ROOT/scripts/patch-alpine-live-iso.sh" \
  && ok "ISO patch ignores NVMe/HDD leftover apkovl" || die "patch missing internal-disk apkovl filter"
grep -q 'Whick: found apkovl' "$ROOT/scripts/patch-alpine-live-iso.sh" \
  && ok "ISO patch injects initramfs apkovl fallback" || die "patch missing Whick apkovl fallback"
! grep -qE '/dev/nvme\*n\*p\*' "$ROOT/scripts/patch-alpine-live-iso.sh" \
  && ok "ISO apkovl fallback does not scan NVMe devices" || die "patch fallback must not scan /dev/nvme*n*p*"
grep -q 'quiet must be removed\|\\bquiet\\b' "$ROOT/scripts/patch-alpine-live-iso.sh" \
  && ok "ISO patch removes quiet from cmdline" || die "patch missing quiet removal"
grep -q 'opt/whick-boot-connect' "$ROOT/scripts/build-connect-usb-package.sh" \
  && ok "apkovl build embeds opt/whick-boot-connect" || die "build script missing apkovl embed"
grep -q 'hw_identity.py' "$ROOT/scripts/build-connect-usb-package.sh" \
  && ok "apkovl build includes hw_identity.py" || die "build script missing hw_identity in apkovl"

grep -q 'protected_paths.d/whick.list' "$ROOT/scripts/build-connect-usb-package.sh" \
  && ok "apkovl protects etc/inittab from apk overwrite" || die "build script missing inittab protect"

! grep -q 'runlevels/boot/networking' "$ROOT/scripts/build-connect-usb-package.sh" \
  && ok "apkovl skips OpenRC networking (whick manages net)" || die "remove networking boot runlevel"

grep -q '/opt/whick-boot-connect' "$ROOT/boot-connect/alpine-local.d-whick-connect.start" \
  && ok "start prefers apkovl /opt/whick-boot-connect" || die "start script missing apkovl path"

grep -q 'whick-boot-sequence' "$ROOT/boot-connect/alpine-local.d-whick-connect.start" \
  && ok "apkovl start → boot-sequence" || die "apkovl start script wrong target"

! grep -q 'HandlePowerKey=ignore' "$ROOT/live/bin/install-runtime.sh" \
  && ok "USB/runtime installer leaves power policy to CC" \
  || die "power policy must run after CC agent link, not in USB/runtime installer"
grep -q "case 'apply_power_policy'" "$ROOT/../agent/src/commands.mjs" \
  && ok "agent supports CC apply_power_policy" || die "agent missing apply_power_policy"
# VERIFY_COMMANDS may be multiline; first entry must still be apply_power_policy.
# SSOT = packages/install (api/src/lib/*.js are thin re-export shims).
python3 - <<'PY' \
  && ok "CC post-install runs power policy first" || die "CC power policy is not first post-install command"
import re
from pathlib import Path
text = Path("/data/whick-ai/2_control_center/api/src/packages/install/lib/installPostVerify.js").read_text()
m = re.search(r"const\s+VERIFY_COMMANDS\s*=\s*\[([^\]]+)\]", text, re.S)
assert m, "VERIFY_COMMANDS missing"
cmds = re.findall(r"'([^']+)'", m.group(1))
assert cmds and cmds[0] == "apply_power_policy", cmds
PY

[[ -f "$ROOT/boot-connect/alpine-local.d-whick-connect.start.good" ]] \
  && ok "wired baseline local.d (from USB설치용.zip)" || die "missing wired baseline local.d"
[[ -f "$ROOT/boot-connect/apkovl-inittab-wired-base" ]] \
  && ok "wired baseline inittab (from USB설치용.zip)" || die "missing wired baseline inittab"

section "Python syntax"
python3 -m py_compile "$ROOT/boot-connect/whick-customer-setup.py" \
  && ok "whick-customer-setup.py compiles" || die "whick-customer-setup.py syntax error"
python3 -m py_compile "$ROOT/boot-connect/hw_identity.py" \
  && ok "hw_identity.py compiles" || die "hw_identity.py syntax error"
grep -q 'HW_ID_SCHEME = "motherboard-v1"' "$ROOT/boot-connect/hw_identity.py" \
  && ok "hw_id motherboard scheme" || die "hw_identity missing motherboard scheme"
grep -q 'collect_dmi_raw_for_server' "$ROOT/boot-connect/whick-boot-connect.sh" \
  && ok "boot-connect uses collect_dmi_raw_for_server (server SSOT hash)" \
  || die "boot-connect missing collect_dmi_raw_for_server"
grep -q 'def collect_dmi_raw_for_server' "$ROOT/boot-connect/hw_identity.py" \
  && ok "hw_identity raw DMI for server" || die "hw_identity missing collect_dmi_raw_for_server"
grep -q 'def resolve_hw_identity' "$ROOT/boot-connect/hw_identity.py" \
  && ok "hw_identity resolve fallback" || die "hw_identity missing resolve_hw_identity"
grep -q '/install/link' "$ROOT/boot-connect/whick-boot-connect.sh" \
  && ok "boot-connect install link phase" || die "boot-connect missing /install/link"
grep -q 'processInstallLink' "/data/whick-ai/2_control_center/api/src/packages/install/routes/install.js" \
  && ok "CC install link route" || die "CC missing processInstallLink route"
! grep -q 'class/net' "$ROOT/boot-connect/hw_identity.py" \
  && ok "hw_identity no NIC MAC" || die "hw_identity must not use NIC MAC"


section "Rescue OFF (install USB)"
grep -q 'WHICK_RESCUE_ENABLE=0' "$ROOT/live/lib/whick-disk.env" \
  && ok "whick-disk.env WHICK_RESCUE_ENABLE=0" || die "whick-disk.env must set WHICK_RESCUE_ENABLE=0"
grep -qE 'os\.environ\.get\("WHICK_RESCUE_ENABLE",\s*"0"\)' "$ROOT/live/bin/disk_plan.py" \
  && ok 'disk_plan default WHICK_RESCUE_ENABLE="0"' || die 'disk_plan must default WHICK_RESCUE_ENABLE to "0"'

section "SUMMARY"
echo ""
if [[ "$FAIL" -gt 0 ]]; then
  echo "SOURCE VERIFY FAILED ($FAIL)" >&2
  exit 1
fi
echo "SOURCE VERIFY OK"
