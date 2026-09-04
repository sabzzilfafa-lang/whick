#!/usr/bin/env bash
# connect-usb 빠른 사전 검증 — ISO/zip/VIP 배포 없이 (약 2–3분)
# 코드 수정 후 release-connect-usb.sh 전에 1회 실행 → 실물 USB 테스트 횟수 절감
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPTS="$ROOT/scripts"
BC="$ROOT/boot-connect"
FAIL=0

die() { echo "  FAIL  $*" >&2; FAIL=$((FAIL + 1)); }
ok()  { echo "  PASS  $*"; }

section() { echo ""; echo "== $* =="; }

section "1. 소스 정적 검증"
"$SCRIPTS/verify-connect-sources.sh"

section "2. Python / Shell 문법"
for py in "$BC"/*.py; do
  [[ -f "$py" ]] || continue
  python3 -m py_compile "$py" && ok "$(basename "$py")" || die "py_compile $(basename "$py")"
done
for sh in "$BC"/*.sh "$BC"/alpine-local.d-whick-connect.start "$BC"/alpine-init.d-whick-modloop; do
  [[ -f "$sh" ]] || continue
  bash -n "$sh" && ok "$(basename "$sh")" || die "bash -n $(basename "$sh")"
done

section "3. apkovl만 빌드 (Docker, ISO·zip 생략)"
export WHICK_USB_PROFILE="${WHICK_USB_PROFILE:-wired}"
export WHICK_CONNECT_ZIP_NAME="${WHICK_CONNECT_ZIP_NAME:-USB설치용-유선.zip}"
export WHICK_CONNECT_APKOVL_ONLY=1
"$SCRIPTS/build-connect-usb-package.sh"

APKOVL="${WHICK_CONNECT_DIST:-/mnt/music/whick-cc/build-staging/connect-usb}/${WHICK_CONNECT_PKG_NAME:-connect-usb-pkg}/alpine.apkovl.tar.gz"
[[ -f "$APKOVL" ]] || { die "apkovl output missing"; section "SUMMARY"; exit 1; }

section "4. apkovl 구조·용량 예산"
python3 - <<PY
import os, sys, tarfile
from pathlib import Path
p = Path("$APKOVL")
fail = 0
def die(msg):
    global fail
    print(f"  FAIL  {msg}", file=sys.stderr)
    fail += 1
def ok(msg):
    print(f"  PASS  {msg}")
size_mb = p.stat().st_size / 1024 / 1024
ok(f"apkovl size {size_mb:.1f} MiB")
profile = os.environ.get("WHICK_USB_PROFILE", "wired")
apkovl_budget = 850 if profile == "wireless" else 620
zip_budget = 2300 if profile == "wireless" else 1400
if size_mb > apkovl_budget:
    die(f"apkovl too large ({size_mb:.0f} MiB > {apkovl_budget} MiB budget)")
with tarfile.open(p) as t:
    names = t.getnames()
    checks = [
        ("etc/local.d/whick-connect.start", "whick-connect.start"),
        ("etc/runlevels/boot/whick-modloop", "whick-modloop boot"),
        ("opt/whick-boot-connect/whick-customer-setup.py", "customer setup"),
        ("opt/whick-boot-connect/hw_identity.py", "hw_identity"),
        ("opt/whick-boot-connect/mini/usr/bin/python3", "mini python3"),
        ("opt/whick-boot-connect/firmware/", "firmware in opt"),
    ]
    for needle, label in checks:
        if any(n == needle or n.startswith(needle) for n in names):
            ok(f"apkovl {label}")
        else:
            die(f"apkovl missing {label}")
    if any("runlevels/boot/local" in n for n in names):
        die("apkovl has boot/local (modloop race)")
    else:
        ok("apkovl no boot/local")
    if any(n.startswith("lib/") for n in names):
        die("apkovl has lib/ overlay")
    else:
        ok("apkovl no lib/ overlay")
    for bad in ("usr/", "bin/", "sbin/"):
        if any(n.startswith(bad) for n in names):
            die(f"apkovl has {bad} overlay (breaks Live fsck)")
        else:
            ok(f"apkovl no {bad} overlay")
    if any("whick.apkovl" in n for n in names):
        die("apkovl contains whick.apkovl duplicate name")
    if any("/phases/" in n for n in names):
        die("apkovl must not embed phase 5~7 scripts (CC server bundle)")
    else:
        ok("apkovl no phase scripts (CC orchestrator)")
    if any(n.endswith("REMOTE-PHASES-CC.txt") for n in names):
        ok("apkovl REMOTE-PHASES-CC marker")
    else:
        die("apkovl missing REMOTE-PHASES-CC.txt")
# zip 예상: apkovl*2 (ISO embed + file) + iso base ~210MB + ventoy ~15MB
est_mb = size_mb * 2 + 220
ok(f"estimated full zip ~{est_mb:.0f} MiB (budget <= {zip_budget} MiB)")
if est_mb > zip_budget:
    die(f"estimated zip exceeds {zip_budget} MiB budget")
sys.exit(fail)
PY
[[ $? -eq 0 ]] || FAIL=$((FAIL + 1))

section "5. boot-connect 핵심 grep"
grep -q 'whick_ensure_modloop' "$BC/alpine-local.d-whick-connect.start" \
  && ok "modloop wait in start" || die "missing modloop wait"
grep -q 'whick-kernel-modules.sh' "$BC/whick-boot-sequence.sh" \
  && ok "boot-sequence loads net modules" || die "boot-sequence missing kernel modules"
grep -q 'connect-usb build' "$BC/alpine-local.d-whick-connect.start" \
  && ok "build stamp in start" || die "missing build stamp (traceability)"
grep -q 'whick-kernel-modules.sh' "$BC/alpine-local.d-whick-connect.start" \
  && ok "start sources whick-kernel-modules" || die "start missing whick-kernel-modules"
grep -q 'request_eth_dhcp' "$BC/whick-customer-setup.py" \
  && ok "lan dhcp helper" || die "missing request_eth_dhcp"

section "SUMMARY"
echo ""
if [[ "$FAIL" -gt 0 ]]; then
  echo "PREFLIGHT FAILED ($FAIL) — release-connect-usb.sh 실행 금지" >&2
  exit 1
fi
echo "PREFLIGHT OK — 이제 release-connect-usb.sh (또는 --skip-publish) 1회만 실행"
echo "실물 USB 테스트는 preflight+release PASS 후에만 진행"
