#!/usr/bin/env bash
# disk_plan.py unit checks (mock lsblk — no real disk)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$ROOT/live/bin/disk_plan.py"
FAIL=0
ok() { echo "  PASS  $*"; }
ng() { echo "  FAIL  $*" >&2; FAIL=$((FAIL + 1)); }

MOCK=/tmp/whick-disk-plan-mock.json
cat >"$MOCK" <<'JSON'
{
  "blockdevices": [
    {"name": "sdb", "path": "/dev/sdb", "size": 536870912000, "type": "disk", "rm": true, "tran": "usb"},
    {
      "name": "nvme0n1", "path": "/dev/nvme0n1", "size": 536870912000, "type": "disk", "rm": false, "tran": "nvme",
      "children": [
        {"name": "nvme0n1p1", "path": "/dev/nvme0n1p1", "size": 107374182400, "type": "part", "fstype": "ext4", "label": "whick-root"},
        {"name": "nvme0n1p2", "path": "/dev/nvme0n1p2", "size": 429496729600, "type": "part", "fstype": "ext4", "label": "whick-music", "mountpoint": "/mnt/music"}
      ]
    }
  ]
}
JSON

export WHICK_LSBLK_JSON="$MOCK"
# inject mock via env — disk_plan uses real lsblk; test via python import
python3 - <<PY
import json, sys, os
sys.path.insert(0, "$ROOT/live/bin")
# Ensure default OFF even if caller exported ENABLE=1
os.environ.pop("WHICK_RESCUE_ENABLE", None)
import disk_plan as dp

tree = json.load(open("$MOCK"))
disk = dp.pick_target_disk(tree)
plan = dp.plan_disk(disk)
assert plan.disk == "/dev/nvme0n1", plan.disk
assert plan.mode == "preserve_music", plan.mode
assert len(plan.preserve) == 1, plan.preserve
assert plan.preserve[0]["path"] == "/dev/nvme0n1p2"
assert "/dev/nvme0n1p2" not in plan.wipe, plan.wipe
assert "/dev/nvme0n1p1" in plan.wipe, plan.wipe
assert plan.install_reserve_gb == 64, plan.install_reserve_gb  # 500GB > 112GiB tier -> 64G
print("  PASS  preserve_music 500GB")

# 재설치(preserve_music) — 기본 WHICK_RESCUE_ENABLE=0 이면 rescue 만들지 않음 (pre-v0.9.3)
assert dp.RESCUE_ENABLE is False, "default RESCUE_ENABLE must be False"
rescue_on_reinstall = [c for c in plan.create if c.get("role") == "rescue"]
assert len(rescue_on_reinstall) == 0, f"default: no rescue create, got {plan.create}"
print("  PASS  preserve_music default OFF — no rescue create")

# ENABLE=1 이면 재설치 시 없는 rescue를 새로 만든다
import importlib
os.environ["WHICK_RESCUE_ENABLE"] = "1"
importlib.reload(dp)
assert dp.RESCUE_ENABLE is True
plan_en = dp.plan_disk(disk)
rescue_on = [c for c in plan_en.create if c.get("role") == "rescue"]
assert len(rescue_on) == 1, plan_en.create
assert rescue_on[0]["size_gb"] == dp.RESCUE_GB
print("  PASS  WHICK_RESCUE_ENABLE=1 reinstall adds missing rescue")

# ENABLE=1 + 기존 rescue → 보존, 중복 create 없음
tree_with_rescue = {
    "blockdevices": [
        {"name": "sdb", "path": "/dev/sdb", "size": 536870912000, "type": "disk", "rm": True, "tran": "usb"},
        {
            "name": "nvme0n1", "path": "/dev/nvme0n1", "size": 536870912000, "type": "disk", "rm": False, "tran": "nvme",
            "children": [
                {"name": "nvme0n1p1", "path": "/dev/nvme0n1p1", "size": 107374182400, "type": "part", "fstype": "ext4", "label": "whick-root"},
                {"name": "nvme0n1p2", "path": "/dev/nvme0n1p2", "size": 3221225472, "type": "part", "fstype": "ext4", "label": "whick-rescue"},
                {"name": "nvme0n1p3", "path": "/dev/nvme0n1p3", "size": 426275504128, "type": "part", "fstype": "ext4", "label": "whick-music", "mountpoint": "/mnt/music"},
            ],
        },
    ]
}
disk3 = dp.pick_target_disk(tree_with_rescue)
plan3 = dp.plan_disk(disk3)
assert not [c for c in plan3.create if c.get("role") == "rescue"], plan3.create
assert any(p.get("label") == "whick-rescue" and p.get("action") == "preserve" for p in plan3.preserve), plan3.preserve
print("  PASS  ENABLE=1 keeps existing rescue (no duplicate create)")

# 기본 OFF + 기존 rescue → wipe 대상 (보존 안 함)
os.environ["WHICK_RESCUE_ENABLE"] = "0"
importlib.reload(dp)
assert dp.RESCUE_ENABLE is False
plan_wipe = dp.plan_disk(disk3)
assert not any(p.get("label") == "whick-rescue" for p in plan_wipe.preserve), plan_wipe.preserve
assert "/dev/nvme0n1p2" in plan_wipe.wipe, plan_wipe.wipe
print("  PASS  default OFF wipes existing rescue (music only preserve)")

# preserve apply — root must start after EFI, not overlap at 1MiB
orig_regions = dp._parted_regions
orig_disk_parts = dp._disk_parts
orig_parted_run = dp._parted_run
orig_partprobe = dp._partprobe
orig_release = dp._release_disk_partitions
orig_mkfs = dp._mkfs
calls = []
def fake_regions(disk):
    return [(3, 102400.0, 476928.0)]  # music p3 at ~100G
def fake_parts(disk):
    out = [
        dp.PartInfo("nvme0n1p3", "/dev/nvme0n1p3", 400 * dp.GIB, "ext4", "whick-music", "", "", "nvme0n1"),
    ]
    n_mkpart = sum(1 for c in calls if c and c[0] == "mkpart")
    if n_mkpart >= 1:
        out.insert(
            0,
            dp.PartInfo("nvme0n1p1", "/dev/nvme0n1p1", 512 * dp.MIB, "", "", "WHICK-EFI", "", "nvme0n1"),
        )
    if n_mkpart >= 2:
        out.insert(
            1,
            dp.PartInfo("nvme0n1p2", "/dev/nvme0n1p2", 100 * dp.GIB, "", "", "", "", "nvme0n1"),
        )
    return sorted(out, key=lambda p: dp._part_num(p.path) or 0)
def fake_run(disk, *args):
    calls.append(args)
def fake_partprobe(disk):
    return None
def fake_release(disk, preserve_paths):
    return None
dp._parted_regions = fake_regions
dp._disk_parts = fake_parts
dp._parted_run = fake_run
dp._partprobe = fake_partprobe
dp._release_disk_partitions = fake_release
dp._mkfs = lambda spec, path: calls.append(("mkfs", spec.get("role"), path))
preserve_plan = dp.DiskPlan(
    disk="/dev/nvme0n1",
    disk_gb=477.0,
    mode="preserve_music",
    uefi=True,
    install_reserve_gb=100,
    music_gb=377.0,
    preserve=[{"path": "/dev/nvme0n1p3", "label": "whick-music", "mount": "/mnt/music", "size_gb": 377.0}],
    wipe=["/dev/nvme0n1p1", "/dev/nvme0n1p2"],
    create=[
        {"role": "efi", "mount": "/boot/efi", "fstype": "vfat", "size_mib": 512},
        {"role": "root", "mount": "/", "fstype": "ext4", "label": "whick-root", "size_gb": 100},
    ],
)
dp._apply_preserve(preserve_plan)
mkpart_calls = [c for c in calls if c and c[0] == "mkpart"]
assert len(mkpart_calls) >= 2, calls
efi_call = mkpart_calls[0]
root_call = mkpart_calls[1]
assert efi_call[3] == "1MiB", efi_call
assert root_call[3] != "1MiB", root_call
assert root_call[3].endswith("MiB") or root_call[3].endswith("GiB"), root_call
dp._parted_regions = orig_regions
dp._disk_parts = orig_disk_parts
dp._parted_run = orig_parted_run
dp._partprobe = orig_partprobe
dp._release_disk_partitions = orig_release
dp._mkfs = orig_mkfs
print("  PASS  preserve apply root after EFI")

# preserve apply — ENABLE=1 일 때 root 뒤 rescue 생성 (opt-in 경로)
os.environ["WHICK_RESCUE_ENABLE"] = "1"
importlib.reload(dp)
calls2 = []
def fake_regions2(disk):
    return [(3, 102400.0, 476928.0)]  # music p3 at ~100G
def fake_parts2(disk):
    out = [
        dp.PartInfo("nvme0n1p3", "/dev/nvme0n1p3", 400 * dp.GIB, "ext4", "whick-music", "", "", "nvme0n1"),
    ]
    n_mkpart = sum(1 for c in calls2 if c and c[0] == "mkpart")
    if n_mkpart >= 1:
        out.insert(0, dp.PartInfo("nvme0n1p1", "/dev/nvme0n1p1", 512 * dp.MIB, "", "", "WHICK-EFI", "", "nvme0n1"))
    if n_mkpart >= 2:
        out.insert(1, dp.PartInfo("nvme0n1p2", "/dev/nvme0n1p2", 64 * dp.GIB, "", "", "", "", "nvme0n1"))
    if n_mkpart >= 3:
        out.insert(2, dp.PartInfo("nvme0n1pX", "/dev/nvme0n1pX", 3 * dp.GIB, "", "", "", "", "nvme0n1"))
    return sorted(out, key=lambda p: dp._part_num(p.path) or 0)
dp._parted_regions = fake_regions2
dp._disk_parts = fake_parts2
dp._parted_run = lambda disk, *args: calls2.append(args)
dp._partprobe = fake_partprobe
dp._release_disk_partitions = fake_release
dp._mkfs = lambda spec, path: calls2.append(("mkfs", spec.get("role"), path))
preserve_plan_rescue = dp.DiskPlan(
    disk="/dev/nvme0n1",
    disk_gb=477.0,
    mode="preserve_music",
    uefi=True,
    install_reserve_gb=64,
    music_gb=377.0,
    preserve=[{"path": "/dev/nvme0n1p3", "label": "whick-music", "mount": "/mnt/music", "size_gb": 377.0}],
    wipe=["/dev/nvme0n1p1", "/dev/nvme0n1p2"],
    create=[
        {"role": "efi", "mount": "/boot/efi", "fstype": "vfat", "size_mib": 512},
        {"role": "root", "mount": "/", "fstype": "ext4", "label": "whick-root", "size_gb": 64},
        {"role": "rescue", "mount": None, "fstype": "ext4", "label": "whick-rescue", "size_gb": 3},
    ],
)
dp._apply_preserve(preserve_plan_rescue)
mkfs_roles = [c[1] for c in calls2 if c and c[0] == "mkfs"]
assert "root" in mkfs_roles and "rescue" in mkfs_roles, calls2
mkpart_calls2 = [c for c in calls2 if c and c[0] == "mkpart"]
assert len(mkpart_calls2) == 3, calls2  # efi + root + rescue
dp._parted_regions = orig_regions
dp._disk_parts = orig_disk_parts
dp._parted_run = orig_parted_run
dp._partprobe = orig_partprobe
dp._release_disk_partitions = orig_release
dp._mkfs = orig_mkfs
print("  PASS  ENABLE=1 preserve apply creates rescue after root")
# fresh 500G — default OFF: no rescue
os.environ["WHICK_RESCUE_ENABLE"] = "0"
importlib.reload(dp)
fresh = {
  "name": "nvme1n1", "path": "/dev/nvme1n1", "size": 536870912000, "type": "disk", "rm": False,
  "children": []
}
plan2 = dp.plan_disk(fresh)
assert plan2.mode == "fresh", plan2.mode
music = next(c for c in plan2.create if c.get("role") == "music")
assert music["size_gb"] >= 340, music
print("  PASS  fresh 500GB music ~", music["size_gb"], "GB")
rescue_parts = [c for c in plan2.create if c.get("role") == "rescue"]
assert len(rescue_parts) == 0, f"default fresh must not create rescue, got {rescue_parts}"
print("  PASS  fresh default OFF — no rescue partition")
# ENABLE=1 fresh has rescue
os.environ["WHICK_RESCUE_ENABLE"] = "1"
importlib.reload(dp)
plan2b = dp.plan_disk(fresh)
rescue_parts_b = [c for c in plan2b.create if c.get("role") == "rescue"]
assert len(rescue_parts_b) == 1 and rescue_parts_b[0]["size_gb"] == dp.RESCUE_GB
print("  PASS  ENABLE=1 fresh has rescue partition")
# restore default for any later imports
os.environ["WHICK_RESCUE_ENABLE"] = "0"
importlib.reload(dp)
PY

python3 -m py_compile "$PY" "$ROOT/live/bin/cc_progress.py" "$ROOT/live/curtin/generate-curtin-config.py"
ok "py_compile disk_plan cc_progress curtin"

[[ "$FAIL" -eq 0 ]] && echo "OK disk-plan tests" || exit 1
