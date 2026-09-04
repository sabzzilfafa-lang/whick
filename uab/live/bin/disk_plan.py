#!/usr/bin/env python3
"""Whick SSD partition planner — preserve /mnt/music, reserve install space.

root(OS+Docker+runtime) 예약은 3단계 고정값(install_reserve_gb 참고):
64G급     (~62 GiB)  → 40G
128G급    (~119 GiB) → 64G (절반)
256G 이상 (~238 GiB) → 128G (절반)
나머지 전부 → /mnt/music (음원저장소).
기존 whick-music 라벨·/mnt/music 파티션은 wipe 대상에서 제외.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# root(OS+Docker+runtime) 예약 — 3단계 고정값 (install_reserve_gb 참고).
# WHICK_INSTALL_RESERVE_GB를 명시하면(랩 테스트 등) 이 3단계를 무시하고 그 값을 강제한다.
# lsblk size는 GiB(1024^3) 기준인데 SSD/eMMC는 보통 GB(10^9, 데시멀) 단위로 표기돼
# "128GB"급 실제 디스크는 lsblk 기준 ~119GiB, "256GB"급은 ~238GiB 로 보인다.
# threshold를 넉넉히 110 / 230 으로 설정해 급간에 여유를 둔다.
ROOT_TIER_128_GB = int(os.environ.get("WHICK_ROOT_TIER_128_GB", "110"))
ROOT_TIER_256_GB = int(os.environ.get("WHICK_ROOT_TIER_256_GB", "230"))
ROOT_62_GB = int(os.environ.get("WHICK_ROOT_62_GB", "40"))
ROOT_128_GB = int(os.environ.get("WHICK_ROOT_128_GB", "64"))
ROOT_256_GB = int(os.environ.get("WHICK_ROOT_256_GB", "128"))
# 레거시 env 호환
ROOT_TIER_THRESHOLD_GB = int(os.environ.get("WHICK_ROOT_TIER_THRESHOLD_GB", "0"))
ROOT_SMALL_GB = int(os.environ.get("WHICK_ROOT_SMALL_GB", "0"))
ROOT_LARGE_GB = int(os.environ.get("WHICK_ROOT_LARGE_GB", "0"))
_INSTALL_RESERVE_OVERRIDE = os.environ.get("WHICK_INSTALL_RESERVE_GB", "").strip()
MUSIC_LABEL = os.environ.get("WHICK_MUSIC_LABEL", "whick-music").strip().lower()
ROOT_LABEL = os.environ.get("WHICK_ROOT_LABEL", "whick-root").strip().lower()
MUSIC_MOUNT = os.environ.get("WHICK_MUSIC_MOUNT", "/mnt/music").rstrip("/")
EFI_SIZE_MIB = int(os.environ.get("WHICK_EFI_SIZE_MIB", "512"))
MUSIC_MIN_GB = int(os.environ.get("WHICK_MUSIC_MIN_GB", "15"))
INSTALL_MIN_GB = int(os.environ.get("WHICK_INSTALL_MIN_GB", "32"))
BOOTSTRAP_ROOT_MIN_GB = int(os.environ.get("WHICK_BOOTSTRAP_ROOT_MIN_GB", "16"))
# 원격(무인) 재설치용 복구 영역 — 기본 OFF (pre-v0.9.3 / 설치 안정화).
# WHICK_RESCUE_ENABLE=1 일 때만 생성·보존·배포. music(/mnt/music) 보존은 항상.
RESCUE_LABEL = os.environ.get("WHICK_RESCUE_LABEL", "whick-rescue").strip().lower()
RESCUE_ENABLE = os.environ.get("WHICK_RESCUE_ENABLE", "0").strip().lower() in ("1", "true", "yes")
RESCUE_GB = int(os.environ.get("WHICK_RESCUE_GB", "3"))
MIB = 1024 * 1024
GIB = 1024**3


@dataclass
class PartInfo:
    name: str
    path: str
    size_bytes: int
    fstype: str = ""
    label: str = ""
    partlabel: str = ""
    mountpoint: str = ""
    pkname: str = ""

    @property
    def size_gb(self) -> float:
        return round(self.size_bytes / GIB, 2)


@dataclass
class DiskPlan:
    disk: str
    disk_gb: float
    mode: str  # fresh | preserve_music | reinstall
    uefi: bool
    install_reserve_gb: int
    music_gb: float
    preserve: list[dict[str, Any]] = field(default_factory=list)
    wipe: list[str] = field(default_factory=list)
    create: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _run(cmd: list[str]) -> str:
    return subprocess.check_output(cmd, stderr=subprocess.DEVNULL, text=True)


def lsblk_json() -> dict:
    mock = os.environ.get("WHICK_LSBLK_JSON", "").strip()
    if mock:
        return json.loads(Path(mock).read_text())

    lsblk = _find_lsblk()
    columns = [
        "NAME,PATH,SIZE,TYPE,FSTYPE,LABEL,PARTLABEL,MOUNTPOINT,PKNAME,RM,RO,TRAN",
        "NAME,PATH,SIZE,TYPE,FSTYPE,LABEL,PARTLABEL,MOUNTPOINT,PKNAME,RM,RO",
        "NAME,PATH,SIZE,TYPE,FSTYPE,LABEL,PARTLABEL,MOUNTPOINT,PKNAME",
    ]
    last_err = ""
    for cols in columns:
        try:
            raw = subprocess.check_output(
                [lsblk, "-J", "-b", "-o", cols],
                stderr=subprocess.PIPE,
                text=True,
            )
            return json.loads(raw)
        except FileNotFoundError:
            raise SystemExit(
                "lsblk not found — USB image must include lsblk package (include lsblk in Live image)"
            ) from None
        except (subprocess.CalledProcessError, json.JSONDecodeError) as exc:
            last_err = str(getattr(exc, "stderr", None) or exc)
            continue
    raise SystemExit(f"lsblk failed: {last_err or 'unknown'}")


def _find_lsblk() -> str:
    for base in (
        os.environ.get("WHICK_LSBLK", ""),
        "lsblk",
        "/opt/whick-boot-connect/mini/bin/lsblk",
        "/opt/whick-boot-connect/mini/usr/bin/lsblk",
    ):
        if not base:
            continue
        if base == "lsblk" or Path(base).is_file():
            return base
    return "lsblk"


def _is_usb_or_live(dev: dict, parents: list[dict]) -> bool:
    if dev.get("rm"):
        return True
    tran = str(dev.get("tran") or "").lower()
    if tran in ("usb", "ieee1394"):
        return True
    name = str(dev.get("name") or "")
    if re.search(r"usb|mmcblk.*boot", name, re.I):
        return True
    for p in parents:
        if p.get("rm") or str(p.get("tran") or "").lower() == "usb":
            return True
    return False


def _live_root_disk_paths(tree: dict | None = None) -> set[str]:
    """Running Live OS disk — never target for SSD install."""
    mock = os.environ.get("WHICK_MOCK_LIVE_ROOT", "").strip()
    if mock:
        out: set[str] = set()
        for part in mock.split(","):
            p = part.strip()
            if not p:
                continue
            out.add(p if p.startswith("/dev/") else f"/dev/{p}")
            out.add(p.removeprefix("/dev/"))
        return out

    out: set[str] = set()
    try:
        src = subprocess.check_output(
            ["findmnt", "-n", "-o", "SOURCE", "/"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except (FileNotFoundError, subprocess.CalledProcessError):
        return out
    if not src:
        return out
    try:
        pk = subprocess.check_output(
            ["lsblk", "-no", "PKNAME", src],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        if pk:
            out.add(f"/dev/{pk}")
            out.add(pk)
    except (FileNotFoundError, subprocess.CalledProcessError):
        pass
    if src.startswith("/dev/"):
        out.add(src)
        base = re.sub(r"p?\d+$", "", src.split("/")[-1])
        if base:
            out.add(f"/dev/{base}")
    if tree:
        for d in _collect_disks_raw(tree):
            path = str(d.get("path") or "")
            if path and (src.startswith(path) or path in out):
                out.add(path)
    return out


def _find_block_node(tree: dict, path: str) -> dict | None:
    want = path.strip()
    want_name = want.removeprefix("/dev/")

    def walk(node: dict) -> dict | None:
        node_path = str(node.get("path") or f"/dev/{node.get('name')}")
        if node_path == want or str(node.get("name") or "") == want_name:
            return node
        for ch in node.get("children") or []:
            hit = walk(ch)
            if hit:
                return hit
        return None

    for d in tree.get("blockdevices") or []:
        hit = walk(d)
        if hit:
            return hit
    return None


def _collect_disks_raw(tree: dict) -> list[dict]:
    out: list[dict] = []
    for d in tree.get("blockdevices") or []:
        if d.get("type") == "disk":
            out.append(d)
    return out


def _collect_disks(tree: dict) -> list[dict]:
    out: list[dict] = []
    blockdevices = tree.get("blockdevices") or []
    live_roots = _live_root_disk_paths(tree)

    def walk(node: dict, ancestors: list[dict]) -> None:
        if node.get("type") == "disk":
            path = str(node.get("path") or f"/dev/{node.get('name')}")
            if path in live_roots:
                return
            if not _is_usb_or_live(node, ancestors):
                out.append(node)
        for ch in node.get("children") or []:
            walk(ch, ancestors + [node])

    for d in blockdevices:
        walk(d, [])
    return out


def _flatten_parts(disk_node: dict) -> list[PartInfo]:
    parts: list[PartInfo] = []
    disk_path = str(disk_node.get("path") or f"/dev/{disk_node.get('name')}")

    def walk(node: dict) -> None:
        if node.get("type") == "part":
            parts.append(
                PartInfo(
                    name=str(node.get("name") or ""),
                    path=str(node.get("path") or ""),
                    size_bytes=int(node.get("size") or 0),
                    fstype=str(node.get("fstype") or ""),
                    label=str(node.get("label") or ""),
                    partlabel=str(node.get("partlabel") or ""),
                    mountpoint=str(node.get("mountpoint") or ""),
                    pkname=str(node.get("pkname") or disk_path.rsplit("/", 1)[-1]),
                )
            )
        for ch in node.get("children") or []:
            walk(ch)

    for ch in disk_node.get("children") or []:
        walk(ch)
    return parts


def _label_matches_music(part: PartInfo) -> bool:
    for raw in (part.label, part.partlabel):
        if raw.strip().lower() in (MUSIC_LABEL, "music", "whick_music"):
            return True
    mp = part.mountpoint.rstrip("/")
    if mp == MUSIC_MOUNT or mp.endswith(MUSIC_MOUNT):
        return True
    return False


def _find_music_partition(parts: list[PartInfo]) -> PartInfo | None:
    for p in parts:
        if _label_matches_music(p):
            return p
    return None


def _label_matches_rescue(part: PartInfo) -> bool:
    for raw in (part.label, part.partlabel):
        if raw.strip().lower() in (RESCUE_LABEL, "rescue", "whick_rescue"):
            return True
    return False


def _find_rescue_partition(parts: list[PartInfo]) -> PartInfo | None:
    for p in parts:
        if _label_matches_rescue(p):
            return p
    return None


# 2번째 이상 SSD — 헤드리스(모니터/키보드 없음) 설치라 고객이 고를 방법이 없으므로
# 전량 /mnt/music/diskN 으로 편입한다. 라벨 whick-music-2, whick-music-3 ... 로 재설치 시에도 보존.
_MUSIC_EXTRA_LABEL_RE = re.compile(r"^" + re.escape(MUSIC_LABEL) + r"-(\d+)$")


def _label_matches_music_extra(part: PartInfo) -> int | None:
    for raw in (part.label, part.partlabel):
        m = _MUSIC_EXTRA_LABEL_RE.match(raw.strip().lower())
        if m:
            return int(m.group(1))
    return None


def _find_music_extra_partition(parts: list[PartInfo]) -> tuple[PartInfo, int] | None:
    for p in parts:
        idx = _label_matches_music_extra(p)
        if idx is not None:
            return p, idx
    return None


def pick_extra_disks(tree: dict, target_path: str) -> list[dict]:
    """OS 대상 디스크를 제외한 나머지 내장 디스크 — 커널 경로순으로 안정적 정렬."""
    disks = _collect_disks(tree)
    extras = [
        d for d in disks
        if str(d.get("path") or f"/dev/{d.get('name')}") != target_path
    ]
    extras.sort(key=lambda d: str(d.get("path") or d.get("name") or ""))
    return extras


def plan_extra_disk(disk_node: dict, assigned_index: int) -> DiskPlan:
    disk_path = str(disk_node.get("path") or f"/dev/{disk_node.get('name')}")
    disk_bytes = int(disk_node.get("size") or 0)
    disk_gb = round(disk_bytes / GIB, 2)
    parts = _flatten_parts(disk_node)
    found = _find_music_extra_partition(parts)

    notes: list[str] = []
    preserve: list[dict[str, Any]] = []
    wipe: list[str] = []
    create: list[dict[str, Any]] = []

    if found:
        part, idx = found
        mount = f"{MUSIC_MOUNT}/disk{idx}"
        preserve.append(
            {
                "path": part.path,
                "label": part.label or f"{MUSIC_LABEL}-{idx}",
                "mount": mount,
                "size_gb": part.size_gb,
                "action": "preserve",
            }
        )
        notes.append(f"preserve extra music disk {disk_path} label={part.label} -> {mount}")
        for p in parts:
            if p.path == part.path:
                continue
            if p.fstype or p.size_bytes > 0:
                wipe.append(p.path)
                notes.append(f"wipe stray partition {p.path} on extra disk {disk_path}")
        music_gb = part.size_gb
        mode = "preserve_music_extra"
    else:
        label = f"{MUSIC_LABEL}-{assigned_index}"
        mount = f"{MUSIC_MOUNT}/disk{assigned_index}"
        for p in parts:
            wipe.append(p.path)
        music_gb = round(max(0.0, disk_gb - 0.01), 2)
        create.append(
            {
                "role": "music_extra",
                "mount": mount,
                "fstype": "ext4",
                "label": label,
                "size_gb": music_gb,
                "action": "create",
            }
        )
        notes.append(f"fresh extra music disk {disk_path} ({disk_gb}G) -> {mount} label={label}")
        mode = "fresh_extra_music"

    return DiskPlan(
        disk=disk_path,
        disk_gb=disk_gb,
        mode=mode,
        uefi=False,
        install_reserve_gb=0,
        music_gb=music_gb,
        preserve=preserve,
        wipe=wipe,
        create=create,
        notes=notes,
    )


def plan_extra_disks(tree: dict | None = None, target_path: str | None = None) -> list[DiskPlan]:
    tree = tree or lsblk_json()
    if target_path is None:
        target = pick_target_disk(tree)
        target_path = str(target.get("path") or f"/dev/{target.get('name')}")
    extras = pick_extra_disks(tree, target_path)
    return [plan_extra_disk(d, i + 2) for i, d in enumerate(extras)]


def _music_floor_gb(disk_total_gb: float) -> int:
    """소형 디스크는 music floor를 낮춰 install 최소(32G) 공간 확보."""
    install_need = INSTALL_MIN_GB + 2
    max_for_music = max(1, int(disk_total_gb) - install_need - 1)
    if disk_total_gb <= MUSIC_MIN_GB + install_need:
        return max(1, int(disk_total_gb * 0.35))
    return min(MUSIC_MIN_GB, max_for_music)


def install_reserve_gb(disk_total_gb: float) -> int:
    """root(OS+Docker+runtime) 예약 — 3단계 고정값.

    partition 크기는 한 번 정하면 재설치 전에 못 바꾸므로 넉넉하게 고정:
      - 64G급 (~62 GiB):  ROOT_62_GB  (40G)
      - 128G급 (~119 GiB): ROOT_128_GB (64G, 절반)
      - 256G 이상:         ROOT_256_GB (128G, 절반)
    WHICK_INSTALL_RESERVE_GB를 명시하면(랩 테스트 등) 3단계 무시하고 그 값 강제.
    레거시 env WHICK_ROOT_TIER_THRESHOLD_GB / WHICK_ROOT_SMALL_GB / WHICK_ROOT_LARGE_GB
    셋 다 명시돼 있으면 구 2단계 로직으로 동작 (하위호환).
    """
    if _INSTALL_RESERVE_OVERRIDE:
        try:
            return max(1, int(_INSTALL_RESERVE_OVERRIDE))
        except ValueError:
            pass
    # legacy 2-tier compat
    if ROOT_TIER_THRESHOLD_GB and ROOT_SMALL_GB and ROOT_LARGE_GB:
        if disk_total_gb <= 0:
            return ROOT_SMALL_GB
        target = ROOT_LARGE_GB if disk_total_gb >= ROOT_TIER_THRESHOLD_GB else ROOT_SMALL_GB
    else:
        if disk_total_gb >= ROOT_TIER_256_GB:
            target = ROOT_256_GB
        elif disk_total_gb >= ROOT_TIER_128_GB:
            target = ROOT_128_GB
        else:
            target = ROOT_62_GB

    music_floor = _music_floor_gb(disk_total_gb)
    max_reserve = int(disk_total_gb) - music_floor - 1
    if max_reserve >= target:
        return target
    # 초소형(랩 루프백 테스트 등) — music floor를 양보해서라도 bootstrap 최소치 확보
    cap = int(disk_total_gb * 0.55)
    small = max(1, min(target, cap))
    fallback = max(target, BOOTSTRAP_ROOT_MIN_GB)
    if disk_total_gb >= fallback + 2:
        small = max(small, min(fallback, cap))
    return small


def _uefi_boot() -> bool:
    forced = os.environ.get("WHICK_FORCE_UEFI", "").strip().lower()
    if forced in ("1", "true", "yes"):
        return True
    if forced in ("0", "false", "no"):
        return False
    return Path("/sys/firmware/efi").is_dir()


def plan_disk(disk_node: dict) -> DiskPlan:
    disk_path = str(disk_node.get("path") or f"/dev/{disk_node.get('name')}")
    disk_bytes = int(disk_node.get("size") or 0)
    disk_gb = round(disk_bytes / GIB, 2)
    parts = _flatten_parts(disk_node)
    music = _find_music_partition(parts)
    uefi = _uefi_boot()
    reserve_gb = install_reserve_gb(disk_gb)
    efi_gb = round(EFI_SIZE_MIB / 1024, 2) if uefi else 0.0

    notes: list[str] = []
    preserve: list[dict[str, Any]] = []
    wipe: list[str] = []
    create: list[dict[str, Any]] = []

    if music:
        mode = "preserve_music"
        music_gb = music.size_gb
        preserve.append(
            {
                "path": music.path,
                "label": music.label or MUSIC_LABEL,
                "mount": MUSIC_MOUNT,
                "size_gb": music_gb,
                "action": "preserve",
            }
        )
        notes.append(f"preserve music partition {music.path} ({music_gb} GB) — never wipe /mnt/music")
        rescue = _find_rescue_partition(parts) if RESCUE_ENABLE else None
        if rescue and RESCUE_ENABLE:
            preserve.append(
                {
                    "path": rescue.path,
                    "label": rescue.label or RESCUE_LABEL,
                    "mount": None,
                    "size_gb": rescue.size_gb,
                    "action": "preserve",
                }
            )
            notes.append(f"preserve rescue partition {rescue.path} ({rescue.size_gb} GB)")
        elif _find_rescue_partition(parts) and not RESCUE_ENABLE:
            notes.append(
                f"WHICK_RESCUE_ENABLE=0 — existing rescue will be wiped (pre-v0.9.3 install path)"
            )
        for p in parts:
            if p.path == music.path or _label_matches_music(p):
                continue
            if music and _part_num(p.path) and _part_num(p.path) == _part_num(music.path):
                continue  # kpartx: /dev/loopNpM ↔ /dev/mapper/loopNpM 동일 파티션
            if rescue and p.path == rescue.path:
                continue
            if rescue and _part_num(p.path) and _part_num(p.path) == _part_num(rescue.path):
                continue
            if p.fstype or p.size_bytes > 0:
                wipe.append(p.path)
                notes.append(f"wipe OS partition {p.path} ({p.fstype or 'unknown'})")
        create.append(
            {
                "role": "root",
                "mount": "/",
                "fstype": "ext4",
                "label": ROOT_LABEL,
                "size_gb": reserve_gb,
            }
        )
        # 기존 장비 재설치(USB) 시 rescue가 없으면 이번 기회에 새로 만든다.
        # root는 매번 wipe+재생성되므로 그 앞쪽 공간에서 rescue 자리를 나눠 확보한다.
        rescue_alloc = 0
        if not rescue and RESCUE_ENABLE:
            rescue_alloc = RESCUE_GB
            create.append(
                {
                    "role": "rescue",
                    "mount": None,
                    "fstype": "ext4",
                    "label": RESCUE_LABEL,
                    "size_gb": rescue_alloc,
                    "action": "create",
                }
            )
            notes.append(f"reinstall: rescue partition missing — create {rescue_alloc}G now")
        if uefi:
            create.insert(
                0,
                {"role": "efi", "mount": "/boot/efi", "fstype": "vfat", "size_mib": EFI_SIZE_MIB},
            )
        available = disk_gb - music_gb - efi_gb
        needed = reserve_gb + rescue_alloc
        if needed > available + 1:
            notes.append(
                f"WARN: install reserve {reserve_gb}G + rescue {rescue_alloc}G > free {available:.1f}G — shrink root target"
            )
            root_spec = next(s for s in create if s.get("role") == "root")
            new_root = max(1, int(available) - rescue_alloc)
            if new_root < BOOTSTRAP_ROOT_MIN_GB and rescue_alloc:
                # root 최소치도 못 채우면 rescue를 포기하고 root에 전부 배정
                create = [s for s in create if s.get("role") != "rescue"]
                notes.append("WARN: not enough room for rescue on reinstall — skipped")
                root_spec["size_gb"] = max(1, int(available))
            else:
                root_spec["size_gb"] = new_root
    else:
        mode = "fresh"
        do_rescue = RESCUE_ENABLE
        rescue_alloc = RESCUE_GB if do_rescue else 0
        remaining = disk_gb - reserve_gb - efi_gb - rescue_alloc - 1
        floor = MUSIC_MIN_GB if remaining >= MUSIC_MIN_GB else 1
        music_gb = round(max(floor, remaining), 2)
        notes.append(
            f"fresh layout: install {reserve_gb}G + rescue {rescue_alloc}G + music ~{music_gb}G on {disk_gb}G disk "
            f"(tier: <{ROOT_TIER_128_GB}G->{ROOT_62_GB}G, <{ROOT_TIER_256_GB}G->{ROOT_128_GB}G, >={ROOT_TIER_256_GB}G->{ROOT_256_GB}G)"
        )
        if parts:
            for p in parts:
                wipe.append(p.path)
        entry_index = 0
        if uefi:
            create.append(
                {"role": "efi", "mount": "/boot/efi", "fstype": "vfat", "size_mib": EFI_SIZE_MIB},
            )
            entry_index += 1
        create.append(
            {
                "role": "root",
                "mount": "/",
                "fstype": "ext4",
                "label": ROOT_LABEL,
                "size_gb": reserve_gb,
            }
        )
        if do_rescue:
            create.append(
                {
                    "role": "rescue",
                    "mount": None,
                    "fstype": "ext4",
                    "label": RESCUE_LABEL,
                    "size_gb": rescue_alloc,
                    "action": "create",
                }
            )
        create.append(
            {
                "role": "music",
                "mount": MUSIC_MOUNT,
                "fstype": "ext4",
                "label": MUSIC_LABEL,
                "size_gb": music_gb,
                "action": "create",
            }
        )

    return DiskPlan(
        disk=disk_path,
        disk_gb=disk_gb,
        mode=mode,
        uefi=uefi,
        install_reserve_gb=reserve_gb,
        music_gb=music_gb if not music else music.size_gb,
        preserve=preserve,
        wipe=wipe,
        create=create,
        notes=notes,
    )


def pick_target_disk(tree: dict | None = None) -> dict:
    tree = tree or lsblk_json()
    disks = _collect_disks(tree)
    if not disks:
        cand = _collect_disks_raw(tree)
        hint = ", ".join(
            f"{d.get('path')} rm={d.get('rm')} tran={d.get('tran') or '?'}"
            for d in cand[:4]
        )
        raise SystemExit(
            "no internal SSD found (USB/Live disks excluded)"
            + (f" — seen: {hint}" if hint else "")
        )
    disks.sort(key=lambda d: int(d.get("size") or 0), reverse=True)
    forced = os.environ.get("WHICK_TARGET_DISK", "").strip()
    if forced:
        for d in disks:
            if d.get("path") == forced or d.get("name") == forced.removeprefix("/dev/"):
                return d
        # lab loop image — type=loop excluded from internal SSD candidates
        hit = _find_block_node(tree, forced)
        if hit and hit.get("type") in ("disk", "loop"):
            return hit
        raise SystemExit(f"WHICK_TARGET_DISK={forced} not found among candidates")
    return disks[0]


def _parted_run(disk: str, *args: str) -> None:
    cmd = ["parted", "-s", disk, *args]
    print(f"[disk_plan] {' '.join(cmd)}", flush=True)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        raise SystemExit(
            f"parted timeout (120s): {' '.join(cmd)} "
            "— wipe Linux partitions on NVMe from Windows, reboot USB, retry"
        )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip().replace("\n", " ")
        low = detail.lower()
        if "in use" in low or "reboot" in low or "busy" in low:
            raise SystemExit(
                f"parted blocked (partition in use): {' '.join(cmd)} — {detail} "
                "— wipe Linux partitions on NVMe from Windows, reboot USB, retry"
            )
        raise SystemExit(f"parted failed ({proc.returncode}): {' '.join(cmd)} — {detail}")


def _parted_print_text(disk: str) -> str:
    proc = subprocess.run(
        ["parted", "-s", disk, "unit", "MiB", "print"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise SystemExit(f"parted print failed: {detail}")
    return proc.stdout or ""


def _parted_regions(disk: str) -> list[tuple[int, float, float]]:
    """Partition number, start MiB, end MiB (from parted unit MiB print)."""
    out: list[tuple[int, float, float]] = []
    for line in _parted_print_text(disk).splitlines():
        m = re.match(r"\s*(\d+)\s+([\d.]+)MiB\s+([\d.]+)MiB", line)
        if m:
            out.append((int(m.group(1)), float(m.group(2)), float(m.group(3))))
    return out


def _disk_size_mib(disk: str) -> float:
    for line in _parted_print_text(disk).splitlines():
        if "/dev/" in line and ":" in line:
            m = re.search(r":\s*([\d.]+)(MiB|GB)", line)
            if m:
                val = float(m.group(1))
                return val * 1024 if m.group(2) == "GB" else val
    regions = _parted_regions(disk)
    if regions:
        return max(end for _, _, end in regions)
    raise SystemExit(f"cannot determine disk size for {disk}")


def _preserve_region_start_mib(disk: str, preserve_paths: set[str]) -> float | None:
    starts: list[float] = []
    for num, start, _end in _parted_regions(disk):
        path = _part_path(disk, num)
        if path in preserve_paths:
            starts.append(start)
    return min(starts) if starts else None


def _partition_end_mib(disk: str, path: str) -> int:
    num = _part_num(path)
    if not num:
        return 1
    for n, _start, end in _parted_regions(disk):
        if n == num:
            return max(1, int(end))
    return 1


def _part_num(path: str) -> int | None:
    base = path.rsplit("/", 1)[-1]
    m = re.match(r".*p(\d+)$", base) or re.match(r"^[^\d]+(\d+)$", base)
    return int(m.group(1)) if m else None


def _resolve_preserve_paths(disk: str, preserve: list[dict[str, Any]]) -> set[str]:
    """Plan JSON 경로가 stale일 수 있음 — 라벨·music 휴리스틱으로 실제 노드 재탐색.

    kpartx 사용 시 같은 파티션이 /dev/loopNpM 과 /dev/mapper/loopNpM 둘 다 보이므로
    번호·라벨이 일치하면 모두 preserve 집합에 넣는다 (wipe가 music을 지우지 않게).
    """
    paths: set[str] = set()
    preserve_labels = {str(x.get("label") or "").strip().lower() for x in preserve}
    preserve_labels.add(MUSIC_LABEL)
    preserve_nums: set[int] = set()
    for item in preserve:
        p = str(item.get("path") or "").strip()
        if p:
            paths.add(p)
            n = _part_num(p)
            if n:
                preserve_nums.add(n)
    for p in _disk_parts(disk):
        n = _part_num(p.path)
        if (
            p.path in paths
            or _label_matches_music(p)
            or p.label.lower() in preserve_labels
            or (n is not None and n in preserve_nums)
        ):
            paths.add(p.path)
            if n:
                preserve_nums.add(n)
                paths.add(_part_path(disk, n))
                paths.add(_resolve_part_path(disk, n))
    return paths


def _release_disk_partitions(
    disk: str, preserve_paths: set[str], *, keep_preserve_mounted: bool = False
) -> None:
    """Umount partitions before wipe/repart.

    Music data partitions stay mounted when preserved *after* apply. During
    parted GPT changes on NVMe, ANY mounted partition on the disk can block
    `parted rm`/`mklabel` (120s timeout) — so keep_preserve_mounted=False
    while rewriting the table.
    """
    # Timeouts: dirty NVMe umount can hang forever and freeze install_linux.
    subprocess.run(["timeout", "10", "umount", "-lf", MUSIC_MOUNT], stderr=subprocess.DEVNULL)
    _umount_disk_from_proc(disk)
    for p in _disk_parts(disk):
        keep_mounted = (
            keep_preserve_mounted
            and p.path in preserve_paths
            and not _label_matches_rescue(p)
        )
        if keep_mounted:
            continue
        if p.fstype.lower() == "swap":
            subprocess.run(["timeout", "10", "swapoff", p.path], stderr=subprocess.DEVNULL)
        if p.mountpoint:
            subprocess.run(
                ["timeout", "15", "umount", "-lf", p.mountpoint], stderr=subprocess.DEVNULL
            )
        subprocess.run(["timeout", "15", "umount", "-lf", p.path], stderr=subprocess.DEVNULL)
        # Do NOT fuser -km here: on some environments (loop/kpartx lab, busybox)
        # it SIGKILLs the installer itself (exit 137). umount -lf is enough.
        _drop_dm_holders(p.path)
    subprocess.run(["timeout", "10", "blockdev", "--rereadpt", disk], stderr=subprocess.DEVNULL)


def _wipe_non_preserve_partitions(disk: str, preserve_paths: set[str]) -> None:
    """현재 파티션 테이블 기준 삭제 — plan.wipe stale·부분 실패 재시도 안전."""
    _release_disk_partitions(disk, preserve_paths)
    preserve_nums = {n for p in preserve_paths if (n := _part_num(p))}
    for num, _start, _end in sorted(_parted_regions(disk), key=lambda x: -x[0]):
        if num in preserve_nums:
            continue
        path = _part_path(disk, num)
        resolved = _resolve_part_path(disk, num)
        if path in preserve_paths or resolved in preserve_paths:
            continue
        part = next(
            (
                p
                for p in _disk_parts(disk)
                if p.path in (path, resolved) or _part_num(p.path) == num
            ),
            None,
        )
        # music always protected; rescue only when ENABLE (otherwise wipe old whick-rescue)
        if part and _label_matches_music(part):
            continue
        if part and RESCUE_ENABLE and _label_matches_rescue(part):
            continue
        _parted_run(disk, "rm", str(num))
    _partprobe(disk)


def _set_esp_flag(disk: str, preserve_paths: set[str]) -> None:
    for p in _disk_parts(disk):
        if p.path in preserve_paths:
            continue
        if _is_efi_part(p) or (not p.fstype and p.size_bytes < 600 * MIB):
            num = _part_num(p.path)
            if num:
                _parted_run(disk, "set", str(num), "esp", "on")
            return


def _part_path(disk: str, num: int) -> str:
    base = disk.rsplit("/", 1)[-1]
    if re.match(r"^(loop|nvme|mmcblk)", base):
        return f"/dev/{base}p{num}"
    return f"/dev/{base}{num}"


def _resolve_part_path(disk: str, num: int) -> str:
    """Nominal path or kpartx mapper — loop kernel-auto nodes can be busy/stale (losetup -P)."""
    base = disk.rsplit("/", 1)[-1]
    if re.match(r"^loop", base):
        # Always prefer mapper on loop (host max_part=0 → /dev/loopNpM often ENXIO/"in use").
        mapper = f"/dev/mapper/{base}p{num}"
        nominal = f"/dev/{base}p{num}"
        if os.path.exists(mapper):
            return mapper
        if os.path.exists(nominal):
            try:
                fd = os.open(nominal, os.O_RDONLY | os.O_EXCL)
                os.close(fd)
                return nominal
            except OSError:
                pass
        return mapper if shutil.which("kpartx") else nominal
    if re.match(r"^(nvme|mmcblk)", base):
        for candidate in (f"/dev/{base}p{num}",):
            if os.path.exists(candidate):
                return candidate
        return f"/dev/{base}p{num}"
    candidate = f"/dev/{base}{num}"
    return candidate if os.path.exists(candidate) else candidate


def _ensure_loop_partitions_enabled() -> None:
    """Lab loop — kernel max_part=0 이면 /dev/loopNpM 노드가 안 생김."""
    try:
        param = Path("/sys/module/loop/parameters/max_part")
        if param.is_file() and int(param.read_text().strip() or "0") == 0:
            subprocess.run(["modprobe", "loop", "max_part=8"], stderr=subprocess.DEVNULL)
    except (OSError, ValueError):
        pass


def _kpartx_refresh(disk: str) -> None:
    """Drop stale maps then re-add — required after parted rm/mkpart on loop."""
    if not shutil.which("kpartx"):
        return
    subprocess.run(["kpartx", "-d", disk], capture_output=True, text=True)
    time.sleep(0.2)
    subprocess.run(["kpartx", "-av", disk], capture_output=True, text=True)
    time.sleep(0.2)


def _kpartx_add(disk: str) -> None:
    if shutil.which("kpartx"):
        subprocess.run(["kpartx", "-av", disk], capture_output=True, text=True)


def _loop_reattach_partscan(disk: str) -> str:
    """max_part 올린 뒤 backing file 재부착 (-P). 경로가 바뀔 수 있음."""
    if not disk.startswith("/dev/loop"):
        return disk
    r = subprocess.run(["losetup", "-n", "-O", "BACK-FILE", disk], capture_output=True, text=True)
    back = (r.stdout or "").strip()
    if not back or not os.path.isfile(back):
        return disk
    subprocess.run(["losetup", "-d", disk], stderr=subprocess.DEVNULL)
    time.sleep(0.3)
    r2 = subprocess.run(["losetup", "-fP", "--show", back], capture_output=True, text=True)
    return (r2.stdout or "").strip() or disk


def _ensure_partition_nodes(disk: str, count: int, *, settle: bool = True) -> list[str]:
    if disk.startswith("/dev/loop"):
        _ensure_loop_partitions_enabled()
    _reread_partitions(disk, settle=settle)
    paths = [_resolve_part_path(disk, i) for i in range(1, count + 1)]
    for _ in range(30):
        if all(os.path.exists(p) for p in paths):
            return paths
        _partx_add(disk)
        if disk.startswith("/dev/loop"):
            _kpartx_add(disk)
        paths = [_resolve_part_path(disk, i) for i in range(1, count + 1)]
        time.sleep(0.5)
    if disk.startswith("/dev/loop"):
        new_disk = _loop_reattach_partscan(disk)
        if new_disk != disk:
            disk = new_disk
            _reread_partitions(disk, settle=settle)
            paths = [_resolve_part_path(disk, i) for i in range(1, count + 1)]
            if all(os.path.exists(p) for p in paths):
                return paths
        _kpartx_add(disk)
        paths = [_resolve_part_path(disk, i) for i in range(1, count + 1)]
        if all(os.path.exists(p) for p in paths):
            return paths
    missing = [p for p in paths if not os.path.exists(p)]
    hint = " (install kpartx or: modprobe loop max_part=8)" if disk.startswith("/dev/loop") else ""
    raise SystemExit(f"partition nodes missing after parted: {missing}{hint}")


def _reread_partitions(disk: str, *, settle: bool = True) -> None:
    subprocess.run(["partprobe", disk], stderr=subprocess.DEVNULL)
    if shutil.which("partx"):
        subprocess.run(["partx", "-a", disk], stderr=subprocess.DEVNULL)
    elif shutil.which("blockdev"):
        subprocess.run(["blockdev", "--rereadpt", disk], stderr=subprocess.DEVNULL)
    if shutil.which("mdev"):
        subprocess.run(["mdev", "-s"], stderr=subprocess.DEVNULL)
    # settle opens partitions via blkid and can leave them EBUSY for mkfs — skip before format
    if settle and shutil.which("udevadm"):
        subprocess.run(["udevadm", "settle", "--timeout=15"], stderr=subprocess.DEVNULL)
    if disk.startswith("/dev/loop"):
        _ensure_loop_partitions_enabled()
        _kpartx_add(disk)
    time.sleep(0.5 if not settle else (2 if shutil.which("partx") else 4))


def _partprobe(disk: str, *, settle: bool = True) -> None:
    _reread_partitions(disk, settle=settle)
    if not shutil.which("partx"):
        print("[disk_plan] partx not found — partprobe/blockdev only", flush=True)


def _partx_add(disk: str) -> None:
    if shutil.which("partx"):
        subprocess.run(["partx", "-a", disk], stderr=subprocess.DEVNULL)
    elif shutil.which("blockdev"):
        subprocess.run(["blockdev", "--rereadpt", disk], stderr=subprocess.DEVNULL)


def _resolve_root_path_after_mkpart(
    disk: str, preserve_paths: list[str], min_start_mib: float
) -> str | None:
    """parted print로 새 root 노드 경로 — lsblk/partx 지연(USB Live) 우회."""
    preserve_nums = {_part_num(p) for p in preserve_paths if _part_num(p)}
    regions = _parted_regions(disk)
    candidates = [
        (num, start, end)
        for num, start, end in regions
        if num not in preserve_nums and start >= min_start_mib - 2
    ]
    if not candidates:
        return None
    num = max(candidates, key=lambda item: item[1])[0]
    # Prefer openable path (mapper on loop) — never return stale /dev/loopNpM just because it exists.
    resolved = _resolve_part_path(disk, num)
    if os.path.exists(resolved):
        try:
            fd = os.open(resolved, os.O_RDONLY)
            os.close(fd)
            return resolved
        except OSError:
            pass
    _reread_partitions(disk)
    if disk.startswith("/dev/loop"):
        _kpartx_refresh(disk)
    for _ in range(40):
        resolved = _resolve_part_path(disk, num)
        if os.path.exists(resolved):
            try:
                fd = os.open(resolved, os.O_RDONLY)
                os.close(fd)
                return resolved
            except OSError:
                pass
        _partx_add(disk)
        if disk.startswith("/dev/loop"):
            _kpartx_refresh(disk)
        time.sleep(0.5)
    return None


def _disk_parts(disk: str) -> list[PartInfo]:
    tree = lsblk_json()
    hit = _find_block_node(tree, disk)
    if hit:
        return sorted(_flatten_parts(hit), key=lambda p: _part_num(p.path) or 0)
    return []


def _stop_block_automount() -> None:
    """Ubuntu Live udisks often remounts NVMe parts between wipefs and mkfs.

    Do NOT udevadm --stop-exec-queue here — parted/partprobe then hang waiting for udev.
    """
    for unit in ("udisks2.service", "udisks2", "gvfs-udisks2-volume-monitor.service"):
        subprocess.run(
            ["timeout", "8", "systemctl", "stop", unit],
            stderr=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
        )


def _resume_block_automount() -> None:
    if shutil.which("udevadm"):
        subprocess.run(["udevadm", "settle", "--timeout=10"], stderr=subprocess.DEVNULL)
    # leave udisks stopped for the rest of install_linux — firstboot can start it later


def _umount_path_from_proc(path: str) -> None:
    """Unmount every /proc/mounts entry that references path (incl. bind/mapper aliases)."""
    targets: list[str] = []
    try:
        with open("/proc/mounts", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                parts = line.split()
                if len(parts) < 2:
                    continue
                src, mnt = parts[0], parts[1]
                if src == path or src.startswith(path + "/") or mnt == path:
                    targets.append(mnt)
    except OSError:
        targets = []
    for mnt in sorted(set(targets), key=len, reverse=True):
        subprocess.run(["timeout", "15", "umount", "-lf", mnt], stderr=subprocess.DEVNULL)
    subprocess.run(["timeout", "15", "umount", "-lf", path], stderr=subprocess.DEVNULL)


def _umount_disk_from_proc(disk: str) -> None:
    """Unmount any mount whose source is disk or disk+partition suffix."""
    targets: list[str] = []
    try:
        with open("/proc/mounts", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                parts = line.split()
                if len(parts) < 2:
                    continue
                src, mnt = parts[0], parts[1]
                if src == disk or src.startswith(disk):
                    targets.append(mnt)
    except OSError:
        return
    for mnt in sorted(set(targets), key=len, reverse=True):
        subprocess.run(["timeout", "15", "umount", "-lf", mnt], stderr=subprocess.DEVNULL)


def _drop_dm_holders(path: str) -> None:
    """Remove device-mapper holders that keep NVMe partitions busy."""
    base = os.path.basename(path)
    holders = Path(f"/sys/class/block/{base}/holders")
    if not holders.is_dir():
        return
    try:
        names = list(holders.iterdir())
    except OSError:
        return
    for h in names:
        name = h.name
        if not name:
            continue
        if shutil.which("dmsetup"):
            subprocess.run(
                ["timeout", "10", "dmsetup", "remove", "--force", name],
                capture_output=True,
                text=True,
            )
        mapper = f"/dev/mapper/{name}"
        if os.path.exists(mapper):
            subprocess.run(["timeout", "10", "umount", "-lf", mapper], stderr=subprocess.DEVNULL)


def _freeze_udev_for_mkfs() -> None:
    """Pause udev workers so blkid does not keep NVMe parts open during mkfs."""
    if shutil.which("udevadm"):
        subprocess.run(["udevadm", "control", "--stop-exec-queue"], stderr=subprocess.DEVNULL)
    # Optional hard stop — ignore failures on minimal live images
    subprocess.run(
        ["timeout", "5", "systemctl", "stop", "systemd-udevd.service"],
        stderr=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
    )


def _thaw_udev_for_mkfs() -> None:
    subprocess.run(
        ["timeout", "8", "systemctl", "start", "systemd-udevd.service"],
        stderr=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
    )
    if shutil.which("udevadm"):
        subprocess.run(["udevadm", "control", "--start-exec-queue"], stderr=subprocess.DEVNULL)
        subprocess.run(["udevadm", "settle", "--timeout=10"], stderr=subprocess.DEVNULL)


def _prepare_part_for_mkfs(path: str) -> None:
    """Clear holders/signatures so mkfs.ext4/vfat does not fail with exit 1 on busy NVMe."""
    _umount_path_from_proc(path)
    _drop_dm_holders(path)
    if shutil.which("pvchange"):
        subprocess.run(["timeout", "10", "pvchange", "-an", path], capture_output=True, text=True)
    if shutil.which("wipefs"):
        subprocess.run(["wipefs", "-af", path], capture_output=True, text=True)
    if shutil.which("blockdev"):
        subprocess.run(["timeout", "10", "blockdev", "--flushbufs", path], stderr=subprocess.DEVNULL)
    _umount_path_from_proc(path)
    time.sleep(0.2)


def _mkfs(spec: dict, path: str) -> None:
    role = spec.get("role")
    print(f"[disk_plan] mkfs {role} on {path}", flush=True)
    if not path or not os.path.exists(path):
        raise SystemExit(f"mkfs target missing: {path}")
    last_err = ""
    _freeze_udev_for_mkfs()
    try:
        for attempt in range(1, 4):
            _prepare_part_for_mkfs(path)
            if role == "efi":
                cmd = ["mkfs.vfat", "-F32", "-I", "-n", "WHICK-EFI", path]
            else:
                label = str(spec.get("label") or ("whick-root" if role == "root" else MUSIC_LABEL)).replace(
                    "_", "-"
                )
                cmd = ["mkfs.ext4", "-F", "-F", "-L", label, path]
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode == 0:
                return
            last_err = (r.stderr or r.stdout or "").strip() or f"exit {r.returncode}"
            print(f"[disk_plan] mkfs retry {attempt}/3 {path}: {last_err[:200]}", flush=True)
            time.sleep(0.8 * attempt)
    finally:
        _thaw_udev_for_mkfs()
    raise SystemExit(f"mkfs failed ({role}) {path}: {last_err}")


def _fmt_mib(mib: int) -> str:
    if mib >= 1024 and mib % 1024 == 0:
        return f"{mib // 1024}GiB"
    return f"{mib}MiB"


def _part_range_mib(start_mib: int, size_mib: int) -> tuple[str, str]:
    return _fmt_mib(start_mib), _fmt_mib(start_mib + size_mib)


def _apply_fresh(plan: DiskPlan) -> None:
    disk = plan.disk
    # Prior OS mounts/holders block mkfs after parted — release before GPT wipe.
    _stop_block_automount()
    _umount_disk_from_proc(disk)
    _release_disk_partitions(disk, set())
    _parted_run(disk, "mklabel", "gpt")
    cur_mib = 1
    idx = 0
    for spec in plan.create:
        role = spec["role"]
        idx += 1
        if role == "efi":
            sz = int(spec["size_mib"])
            s, e = _part_range_mib(cur_mib, sz)
            _parted_run(disk, "mkpart", "EFI", "fat32", s, e)
            _parted_run(disk, "set", str(idx), "esp", "on")
            cur_mib += sz
        elif role == "root":
            sz = int(spec.get("size_gb") or plan.install_reserve_gb) * 1024
            s, e = _part_range_mib(cur_mib, sz)
            _parted_run(disk, "mkpart", "primary", "ext4", s, e)
            cur_mib += sz
        elif role == "rescue":
            sz = int(spec.get("size_gb") or RESCUE_GB) * 1024
            s, e = _part_range_mib(cur_mib, sz)
            _parted_run(disk, "mkpart", "primary", "ext4", s, e)
            cur_mib += sz
        elif role == "music":
            _parted_run(disk, "mkpart", "primary", "ext4", _fmt_mib(cur_mib), "100%")
    _partprobe(disk, settle=False)
    specs = list(plan.create)
    paths = _ensure_partition_nodes(disk, len(specs), settle=False)
    for spec, path in zip(specs, paths):
        _mkfs(spec, path)


def _apply_preserve(plan: DiskPlan) -> None:
    disk = plan.disk
    preserve_paths = _resolve_preserve_paths(disk, plan.preserve)
    if not preserve_paths and plan.preserve:
        raise SystemExit("preserve partition not found on disk — check music label / mount")

    _wipe_non_preserve_partitions(disk, preserve_paths)

    ceiling_mib = _preserve_region_start_mib(disk, preserve_paths)
    if ceiling_mib is None:
        ceiling_mib = _disk_size_mib(disk) - 1

    cur_mib = 1
    parts = _disk_parts(disk)
    has_efi = any(_is_efi_part(p) for p in parts)

    if plan.uefi and not has_efi:
        for spec in plan.create:
            if spec.get("role") == "efi":
                efi_mib = int(spec.get("size_mib") or EFI_SIZE_MIB)
                if cur_mib + efi_mib >= ceiling_mib - 32:
                    raise SystemExit(
                        f"no room for EFI before preserved volume (ceiling {int(ceiling_mib)}MiB)"
                    )
                s, e = _part_range_mib(cur_mib, efi_mib)
                _parted_run(disk, "mkpart", "EFI", "fat32", s, e)
                _partprobe(disk, settle=False)
                _set_esp_flag(disk, preserve_paths)
                cur_mib += efi_mib
                break
    elif plan.uefi and has_efi:
        efi_parts = [p for p in _disk_parts(disk) if _is_efi_part(p)]
        if efi_parts:
            ep = efi_parts[0]
            # Preserve reinstall often keeps OEM/ESP without WHICK-EFI label — relabel for deploy.
            if not ep.fstype:
                efi_spec = next((s for s in plan.create if s.get("role") == "efi"), {"role": "efi"})
                _mkfs(efi_spec, ep.path)
            elif ep.label.strip().upper() != "WHICK-EFI":
                print(f"[disk_plan] relabel EFI {ep.path} ({ep.label!r} -> WHICK-EFI)", flush=True)
                labeled = False
                for tool in ("fatlabel", "dosfslabel"):
                    if shutil.which(tool):
                        r = subprocess.run(
                            [tool, ep.path, "WHICK-EFI"], capture_output=True, text=True
                        )
                        if r.returncode == 0:
                            labeled = True
                            break
                if not labeled:
                    print(f"[disk_plan] WARN could not fatlabel {ep.path}", flush=True)
            cur_mib = _partition_end_mib(disk, ep.path) + 1

    root_spec = next((s for s in plan.create if s.get("role") == "root"), None)
    if not root_spec:
        print("[disk_plan] preserve-only — wipe complete", flush=True)
        return

    rescue_spec = next((s for s in plan.create if s.get("role") == "rescue"), None)
    root_gb = int(root_spec.get("size_gb") or plan.install_reserve_gb)
    root_mib = root_gb * 1024
    rescue_mib = int(rescue_spec.get("size_gb") or RESCUE_GB) * 1024 if rescue_spec else 0
    max_total_mib = int(ceiling_mib) - cur_mib - 1
    min_root_mib = BOOTSTRAP_ROOT_MIN_GB * 1024
    if max_total_mib < min_root_mib:
        raise SystemExit(
            f"insufficient space before music for root: need ~{BOOTSTRAP_ROOT_MIN_GB}G, "
            f"have {max(0, max_total_mib) // 1024}G (ceiling {int(ceiling_mib)}MiB, cur {cur_mib}MiB)"
        )
    if max_total_mib < root_mib + rescue_mib:
        use_root_mib = min(root_mib, max_total_mib)
        rescue_mib = max(0, max_total_mib - use_root_mib)
        if rescue_spec and rescue_mib <= 0:
            print("[disk_plan] WARN: no room for rescue partition beside preserved music — skipped", flush=True)
    else:
        use_root_mib = root_mib

    s, e = _part_range_mib(cur_mib, use_root_mib)
    _parted_run(disk, "mkpart", "primary", "ext4", s, e)
    _partprobe(disk, settle=False)
    if disk.startswith("/dev/loop"):
        _kpartx_refresh(disk)
    # Do NOT kpartx real NVMe/SATA — mapper holders cause mkfs EBUSY on /dev/nvme0n1pN
    root_path = _resolve_root_path_after_mkpart(disk, preserve_paths, cur_mib)
    if not root_path:
        parts = _disk_parts(disk)
        for p in parts:
            if p.path in preserve_paths:
                continue
            if _is_efi_part(p):
                if not p.fstype:
                    efi_spec = next((s for s in plan.create if s.get("role") == "efi"), None)
                    if efi_spec:
                        _mkfs(efi_spec, p.path)
                continue
            if p.fstype:
                continue
            if p.label.lower() == ROOT_LABEL:
                continue
            root_path = p.path
            break
    if not root_path:
        raise SystemExit("failed to create root partition beside preserved music volume")
    _mkfs(root_spec, root_path)
    cur_mib += use_root_mib

    if rescue_spec and rescue_mib > 0:
        rs, re_ = _part_range_mib(cur_mib, rescue_mib)
        _parted_run(disk, "mkpart", "primary", "ext4", rs, re_)
        _partprobe(disk, settle=False)
        rescue_preserve = set(preserve_paths) | {root_path}
        rescue_path = _resolve_root_path_after_mkpart(disk, rescue_preserve, cur_mib)
        if not rescue_path:
            for p in _disk_parts(disk):
                if p.path in rescue_preserve or _is_efi_part(p) or p.fstype:
                    continue
                rescue_path = p.path
                break
        if rescue_path:
            _mkfs(rescue_spec, rescue_path)
        else:
            print("[disk_plan] WARN: failed to create rescue partition — continuing without it", flush=True)


def _is_efi_part(part: PartInfo) -> bool:
    if part.fstype.lower() in ("vfat", "fat32", "fat"):
        return True
    for raw in (part.label, part.partlabel):
        u = raw.strip().upper()
        if u in ("WHICK-EFI", "EFI", "ESP"):
            return True
    return False


def _linux_install_dry_run() -> bool:
    if os.environ.get("WHICK_PROD_INSTALL", "0") in ("1", "true", "yes"):
        return os.environ.get("WHICK_LINUX_INSTALL_DRY_RUN", "0") in ("1", "true", "yes")
    return os.environ.get("WHICK_LINUX_INSTALL_DRY_RUN", "1") in ("1", "true", "yes")


def apply_plan(plan: DiskPlan, *, dry_run: bool = True) -> None:
    """parted apply — destructive. Requires WHICK_DISK_APPLY=1, dry_run=False, WHICK_LINUX_INSTALL_DRY_RUN=0."""
    if (
        dry_run
        or _linux_install_dry_run()
        or os.environ.get("WHICK_DISK_APPLY", "0") not in ("1", "true", "yes")
    ):
        print(json.dumps({"dry_run": True, "plan": plan.to_dict()}, indent=2, ensure_ascii=False))
        return

    live_roots = _live_root_disk_paths(lsblk_json())
    if plan.disk in live_roots:
        raise SystemExit(f"refusing to partition live/USB root disk {plan.disk}")

    print(f"[disk_plan] APPLY mode={plan.mode} disk={plan.disk}", flush=True)
    _stop_block_automount()
    _umount_disk_from_proc(plan.disk)
    try:
        if plan.mode == "fresh" and not plan.preserve:
            _apply_fresh(plan)
        else:
            _apply_preserve(plan)
    finally:
        _resume_block_automount()

    print(
        json.dumps(
            {
                "applied": True,
                "disk": plan.disk,
                "mode": plan.mode,
                "note": "partition layout applied — OS rootfs via whick-bootstrap.img (next)",
            },
            indent=2,
            ensure_ascii=False,
        )
    )


def apply_extra_plan(plan: DiskPlan, *, dry_run: bool = True) -> None:
    """2번째 이상 SSD 전체를 /mnt/music/diskN 으로 편입 — destructive (fresh_extra_music만 wipe)."""
    if (
        dry_run
        or _linux_install_dry_run()
        or os.environ.get("WHICK_DISK_APPLY", "0") not in ("1", "true", "yes")
    ):
        print(json.dumps({"dry_run": True, "plan": plan.to_dict()}, indent=2, ensure_ascii=False))
        return

    live_roots = _live_root_disk_paths(lsblk_json())
    if plan.disk in live_roots:
        raise SystemExit(f"refusing to partition live/USB root disk {plan.disk}")

    disk = plan.disk
    print(f"[disk_plan] APPLY extra mode={plan.mode} disk={disk}", flush=True)

    if plan.mode == "preserve_music_extra":
        preserve_paths = {str(p.get("path") or "") for p in plan.preserve if p.get("path")}
        if not preserve_paths:
            raise SystemExit(f"extra disk preserve partition not found on {disk}")
        _wipe_non_preserve_partitions(disk, preserve_paths)
        print(f"[disk_plan] extra disk {disk} preserve-only — existing music retained")
        return

    if plan.mode != "fresh_extra_music" or not plan.create:
        raise SystemExit(f"unexpected extra disk plan mode: {plan.mode}")

    _release_disk_partitions(disk, set())
    _parted_run(disk, "mklabel", "gpt")
    _parted_run(disk, "mkpart", "primary", "ext4", "1MiB", "100%")
    _partprobe(disk)
    spec = plan.create[0]
    paths = _ensure_partition_nodes(disk, 1)
    _mkfs(spec, paths[0])
    print(f"[disk_plan] extra disk {disk} formatted -> {spec.get('mount')}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Whick SSD partition plan")
    ap.add_argument("--plan", action="store_true", help="print JSON plan for target disk")
    ap.add_argument("--output", "-o", help="write plan JSON to file")
    ap.add_argument("--plan-file", help="read plan JSON for --apply")
    ap.add_argument("--apply", action="store_true", help="apply partition layout (destructive)")
    ap.add_argument("--list", action="store_true", help="list candidate disks")
    ap.add_argument(
        "--plan-extra",
        action="store_true",
        help="print JSON plan array for extra (non-target) disks -> /mnt/music/diskN",
    )
    ap.add_argument(
        "--apply-extra",
        action="store_true",
        help="apply extra disk plans from --plan-file (destructive, array of plans)",
    )
    args = ap.parse_args()

    if args.list:
        tree = lsblk_json()
        cand = [
            {
                "path": d.get("path"),
                "size_gb": round(int(d.get("size") or 0) / GIB, 2),
                "name": d.get("name"),
            }
            for d in _collect_disks(tree)
        ]
        print(json.dumps(cand, indent=2))
        return

    if args.apply:
        if not args.plan_file:
            sys.exit("--apply requires --plan-file")
        data = json.loads(Path(args.plan_file).read_text())
        plan = DiskPlan(**{k: data[k] for k in DiskPlan.__dataclass_fields__ if k in data})
        apply_plan(plan, dry_run=os.environ.get("WHICK_DISK_APPLY", "0") not in ("1", "true", "yes"))
        return

    if args.plan_extra:
        tree = lsblk_json()
        target = pick_target_disk(tree)
        target_path = str(target.get("path") or f"/dev/{target.get('name')}")
        extras = plan_extra_disks(tree, target_path)
        payload = [p.to_dict() for p in extras]
        text = json.dumps(payload, indent=2, ensure_ascii=False)
        if args.output:
            Path(args.output).write_text(text + "\n")
        print(text)
        return

    if args.apply_extra:
        if not args.plan_file:
            sys.exit("--apply-extra requires --plan-file")
        data = json.loads(Path(args.plan_file).read_text())
        if not isinstance(data, list):
            sys.exit("--apply-extra plan file must be a JSON array")
        for item in data:
            plan = DiskPlan(**{k: item[k] for k in DiskPlan.__dataclass_fields__ if k in item})
            apply_extra_plan(plan, dry_run=os.environ.get("WHICK_DISK_APPLY", "0") not in ("1", "true", "yes"))
        return

    disk = pick_target_disk()
    plan = plan_disk(disk)
    payload = plan.to_dict()
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
