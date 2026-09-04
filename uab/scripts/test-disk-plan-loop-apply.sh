#!/usr/bin/env bash
# Scratch: disk_plan.py real loop apply (RESCUE=0) — dirty / reinstall
set -euo pipefail

LIVE_BIN="/data/whick-ai_music_server/3_product/uab/live/bin"
LIVE_LIB="/data/whick-ai_music_server/3_product/uab/live/lib"
SCRATCH="${WHICK_DISK_SCRATCH:-/mnt/ssd2/scratch/disk-plan-virt}"
IMG_GB="${WHICK_DISK_SCRATCH_GB:-64}"
STAMP="$(date +%Y%m%d-%H%M%S)"
WORK="$SCRATCH/$STAMP"
LOG="$WORK/run.log"
INNER="$WORK/inner.sh"

mkdir -p "$WORK"

cat >"$INNER" <<'INNER'
set -euo pipefail
apk add --no-cache python3 parted e2fsprogs dosfstools util-linux multipath-tools >/dev/null
# loop max_part=0 → 4번째 파티션 노드 누락 방지
modprobe loop max_part=31 2>/dev/null || true
if [ -f /sys/module/loop/parameters/max_part ]; then
  echo "loop max_part=$(cat /sys/module/loop/parameters/max_part)"
fi

cd /work
truncate -s "${IMG_GB}G" nvme-sim.img
mkdir -p /work/mnt-music /work/mnt-rescue /work/mnt-root

part_by_label() {
  local loop="$1" label="$2"
  lsblk -lnpo NAME,LABEL "$loop" | awk -v l="$label" '$2==l{print $1; exit}'
}

part_dev() {
  local n="$1"
  base=$(basename "$LOOP")
  if [ -b "/dev/mapper/${base}p$n" ]; then echo "/dev/mapper/${base}p$n"; return; fi
  if [ -b "${LOOP}p$n" ]; then echo "${LOOP}p$n"; return; fi
  echo ""
}

attach() { losetup -fP --show /work/nvme-sim.img; }

detach_clean() {
  local loop="$1"
  umount -lf /work/mnt-music /work/mnt-rescue /work/mnt-root 2>/dev/null || true
  lsblk -lnpo NAME,MOUNTPOINT "$loop" 2>/dev/null | awk 'NF==2{print $2}' | while read -r mp; do
    umount -lf "$mp" 2>/dev/null || true
  done
  kpartx -d "$loop" 2>/dev/null || true
  losetup -d "$loop" 2>/dev/null || true
  sleep 0.5
}

apply_once() {
  local tag="$1" loop="$2"
  echo ""
  echo "----- apply: $tag on $loop -----"
  lsblk -f "$loop" || true
  export WHICK_RESCUE_ENABLE=0
  export WHICK_DISK_APPLY=1
  export WHICK_TARGET_DISK="$loop"
  set -a
  # shellcheck disable=SC1091
  [ -f /live/lib/whick-disk.env ] && . /live/lib/whick-disk.env
  set +a
  export WHICK_RESCUE_ENABLE=0

  local plan="/work/plan-${tag}.json" err="/work/plan-${tag}.err"
  if ! python3 /live/bin/disk_plan.py --plan -o "$plan" 2>"$err"; then
    echo "PLAN FAIL $tag"; cat "$err"; return 1
  fi
  [[ -s "$plan" ]] || { echo "PLAN empty $tag"; cat "$err"; return 1; }
  python3 - <<PY
import json
d=json.load(open("$plan"))
print("mode", d.get("mode"))
print("wipe", d.get("wipe"))
print("preserve", d.get("preserve"))
print("roles", [c.get("role") for c in d.get("create",[])])
roles=[c.get("role") for c in d.get("create",[])]
assert "rescue" not in roles, roles
PY
  if ! WHICK_DISK_APPLY=1 WHICK_LINUX_INSTALL_DRY_RUN=0 WHICK_PROD_INSTALL=1 \
      WHICK_RESCUE_ENABLE=0 WHICK_TARGET_DISK="$loop" \
      python3 /live/bin/disk_plan.py --apply --plan-file "$plan" 2>>"$err"; then
    echo "APPLY FAIL $tag"; tail -60 "$err"; return 1
  fi
  # dry-run would leave no partitions on fresh
  if [[ "$tag" == A_* ]] && ! lsblk -lnpo NAME "$loop" | tail -n +2 | grep -q .; then
    echo "FAIL: apply left no partitions (dry-run?) $tag"
    echo "err:"; cat "$err" || true
    return 1
  fi
  partprobe "$loop" 2>/dev/null || true
  sleep 1
  echo "AFTER $tag:"; lsblk -f "$loop"
  if lsblk -no LABEL "$loop" 2>/dev/null | grep -qi rescue; then
    echo "FAIL: rescue label still present ($tag)"
    return 1
  fi
  echo "OK $tag"
}

echo "===== A fresh RESCUE=0 ====="
LOOP=$(attach)
apply_once A_fresh_rescue_off "$LOOP"
detach_clean "$LOOP"

echo ""
echo "===== seed dirty EFI+root+rescue+music ====="
# fresh image (avoid stale partition nodes from A)
detach_clean "$LOOP" 2>/dev/null || true
# drop any leftover loops on our img
losetup -a 2>/dev/null | awk -F: '/nvme-sim.img/{print $1}' | while read -r L; do
  kpartx -d "$L" 2>/dev/null || true
  losetup -d "$L" 2>/dev/null || true
done
rm -f /work/nvme-sim.img
truncate -s "${IMG_GB}G" /work/nvme-sim.img
LOOP=$(attach)
[ -b "$LOOP" ] || { echo "FAIL: attach after recreate"; losetup -a; exit 1; }
wipefs -af "$LOOP" >/dev/null 2>&1 || true
parted -s "$LOOP" mklabel gpt
# Seed: ~19G before music so reinstall root (>=16G min) fits on 64G image
parted -s "$LOOP" mkpart ESP fat32 1MiB 513MiB
parted -s "$LOOP" set 1 esp on
parted -s "$LOOP" mkpart root ext4 513MiB 16385MiB
parted -s "$LOOP" mkpart rescue ext4 16385MiB 19457MiB
parted -s "$LOOP" mkpart music ext4 19457MiB 100%
partprobe "$LOOP" || true
partx -u "$LOOP" 2>/dev/null || true
kpartx -av "$LOOP" >/work/kpartx-seed.txt 2>&1 || true
cat /work/kpartx-seed.txt || true
# resolve pN: prefer kpartx mapper (max_part=0 host)
part_dev() {
  local n="$1"
  base=$(basename "$LOOP")
  if [ -b "/dev/mapper/${base}p$n" ]; then echo "/dev/mapper/${base}p$n"; return; fi
  if [ -b "${LOOP}p$n" ]; then echo "${LOOP}p$n"; return; fi
  echo ""
}
i=1
while [ "$i" -le 4 ]; do
  n=0
  d=$(part_dev "$i")
  while [ -z "$d" ] && [ "$n" -lt 40 ]; do
    partprobe "$LOOP" 2>/dev/null || true
    kpartx -av "$LOOP" >/dev/null 2>&1 || true
    sleep 0.25
    d=$(part_dev "$i")
    n=$((n + 1))
  done
  [ -n "$d" ] || { echo "FAIL: missing part $i on $LOOP"; ls -l ${LOOP}* /dev/mapper/ 2>/dev/null | head -40; parted -s "$LOOP" print; exit 1; }
  eval "SP$i=$d"
  i=$((i + 1))
done
echo "PARTS: $SP1 $SP2 $SP3 $SP4"
mkfs.vfat -n WHICK-EFI "$SP1" >/dev/null
mkfs.ext4 -F -L whick-root "$SP2" >/dev/null
mkfs.ext4 -F -L whick-rescue "$SP3" >/dev/null
mkfs.ext4 -F -L whick-music "$SP4" >/dev/null
mount "$SP4" /work/mnt-music
echo "KEEP-ME-MUSIC" >/work/mnt-music/PROOF.txt
umount /work/mnt-music
lsblk -f "$LOOP"

echo ""
echo "===== B reinstall with rescue+music mounted ====="
mount "$(part_by_label "$LOOP" whick-rescue)" /work/mnt-rescue
mount "$(part_by_label "$LOOP" whick-music)" /work/mnt-music
echo "busy mounts: rescue+music"
apply_once B_reinstall_wipe_rescue "$LOOP"
umount -lf /work/mnt-rescue /work/mnt-music 2>/dev/null || true
P4=$(part_by_label "$LOOP" whick-music)
[[ -n "$P4" ]] || { echo "FAIL: no music after B"; exit 1; }
mount "$P4" /work/mnt-music
grep -q KEEP-ME-MUSIC /work/mnt-music/PROOF.txt || { echo "FAIL: music wiped"; exit 1; }
echo "music PROOF ok"
umount /work/mnt-music
detach_clean "$LOOP"

echo ""
echo "===== C second reinstall ====="
LOOP=$(attach)
kpartx -av "$LOOP" >/dev/null 2>&1 || true
P4=$(part_by_label "$LOOP" whick-music)
[ -n "$P4" ] || P4=$(part_dev 4)
mount "$P4" /work/mnt-music
apply_once C_second_reinstall "$LOOP"
umount -lf /work/mnt-music 2>/dev/null || true
kpartx -av "$LOOP" >/dev/null 2>&1 || true
P4=$(part_by_label "$LOOP" whick-music)
[ -n "$P4" ] || P4=$(part_dev 4)
mount "$P4" /work/mnt-music
grep -q KEEP-ME-MUSIC /work/mnt-music/PROOF.txt || { echo "FAIL: music wiped on C"; exit 1; }
echo "music PROOF still ok after C"
umount /work/mnt-music
detach_clean "$LOOP"

echo ""
echo "========== ALL VIRTUAL SCENARIOS OK =========="
INNER

{
  echo "========== disk_plan virtual apply $STAMP =========="
  echo "WORK=$WORK IMG=${IMG_GB}G"
  docker run --rm --privileged \
    -v "$LIVE_BIN:/live/bin:ro" \
    -v "$LIVE_LIB:/live/lib:ro" \
    -v "$WORK:/work" \
    -e IMG_GB="$IMG_GB" \
    alpine:3.21 \
    sh /work/inner.sh
  echo "OK disk_plan virtual @ $WORK"
} 2>&1 | tee "$LOG"
