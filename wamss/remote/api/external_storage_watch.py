"""외장 스토리지(USB·NAS·DAS) 감지 · 자동/수동 검수 · 라이브러리 추가 SSOT."""
from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from shutil import copy2
from typing import Any

from api.library_scanner import (
    AUDIO_EXTS,
    evaluate_audit_settings,
    evaluate_hires,
    import_incoming_files,
    load_audit_settings,
)

STATE_PATH = Path(os.getenv("WHICK_EXTERNAL_STORAGE_STATE", "/var/lib/whick/state/external_storage.json"))
MOUNTS_PROC = Path("/host/proc/mounts") if Path("/host/proc/mounts").is_file() else Path("/proc/mounts")

SKIP_MOUNT_PREFIXES = (
    "/boot",
    "/efi",
    "/snap",
    "/var/lib/docker",
    "/var/lib/whick",
    "/mnt/music",
)
NETWORK_FS = {"nfs", "nfs4", "cifs", "smbfs", "fuse.sshfs", "fuse.rclone", "fuse.glusterfs"}


@dataclass
class ExternalMount:
    mount_point: str
    label: str
    device: str
    fs_type: str
    audio_files: int
    size_bytes: int = 0
    source: str = "unknown"  # usb | network | media


def _read_lsblk() -> list[dict[str, str]]:
    try:
        out = subprocess.run(
            ["lsblk", "-J", "-o", "NAME,TYPE,MOUNTPOINT,RM,SIZE,MODEL,LABEL,FSTYPE"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        if out.returncode != 0:
            return []
        data = json.loads(out.stdout or "{}")
        rows: list[dict[str, str]] = []

        def walk(nodes):
            for node in nodes or []:
                rows.append(
                    {
                        "name": str(node.get("name", "")),
                        "type": str(node.get("type", "")),
                        "mountpoint": str(node.get("mountpoint") or ""),
                        "rm": str(node.get("rm", "")),
                        "size": str(node.get("size", "")),
                        "model": str(node.get("model", "")),
                        "label": str(node.get("label", "")),
                        "fstype": str(node.get("fstype", "")),
                    },
                )
                walk(node.get("children"))

        walk(data.get("blockdevices"))
        return rows
    except Exception:
        return []


def _read_proc_mounts() -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    try:
        raw = MOUNTS_PROC.read_text(encoding="utf-8", errors="replace")
        for line in raw.splitlines():
            parts = line.split()
            if len(parts) < 3:
                continue
            device, mount, fstype = parts[0], parts[1], parts[2]
            rows.append((device, mount, fstype.rstrip(",")))
    except OSError:
        pass
    return rows


def _is_skip_mount(mount: str) -> bool:
    m = mount.strip()
    if not m or m == "/":
        return True
    for prefix in SKIP_MOUNT_PREFIXES:
        if m == prefix or m.startswith(prefix + "/"):
            return True
    return False


def _count_audio_files(root: Path, limit: int = 12000) -> tuple[int, int]:
    total = 0
    size = 0
    try:
        for dirpath, _, filenames in os.walk(root):
            for name in filenames:
                if Path(name).suffix.lower() not in AUDIO_EXTS:
                    continue
                total += 1
                fp = Path(dirpath) / name
                try:
                    size += fp.stat().st_size
                except OSError:
                    pass
                if total >= limit:
                    return total, size
    except OSError:
        pass
    return total, size


def _list_audio_rel_paths(root: Path, rel_filter: set[str] | None = None, limit: int = 5000) -> list[str]:
    out: list[str] = []
    try:
        for dirpath, _, filenames in os.walk(root):
            for name in filenames:
                if Path(name).suffix.lower() not in AUDIO_EXTS:
                    continue
                fp = Path(dirpath) / name
                rel = str(fp.relative_to(root)).replace("\\", "/")
                if rel_filter is not None and rel not in rel_filter:
                    continue
                out.append(rel)
                if len(out) >= limit:
                    return out
    except OSError:
        pass
    return sorted(out)


def detect_external_mounts() -> list[ExternalMount]:
    """USB·NAS·DAS·/media 마운트 중 음원이 있는 외부 스토리지."""
    mounts: list[ExternalMount] = []
    seen: set[str] = set()

    def add_mount(mount: str, label: str, device: str, fs_type: str, source: str) -> None:
        if not mount or mount in seen or _is_skip_mount(mount):
            return
        p = Path(mount)
        if not p.is_dir():
            return
        audio_count, audio_size = _count_audio_files(p)
        if audio_count <= 0:
            return
        seen.add(mount)
        mounts.append(
            ExternalMount(
                mount_point=mount,
                label=label or p.name,
                device=device,
                fs_type=fs_type,
                audio_files=audio_count,
                size_bytes=audio_size,
                source=source,
            ),
        )

    for row in _read_lsblk():
        mount = (row.get("mountpoint") or "").strip()
        if not mount:
            continue
        rm = row.get("rm") in ("1", "true", "True")
        model = (row.get("model") or "").lower()
        is_usbish = rm or "usb" in model
        if not is_usbish:
            continue
        add_mount(
            mount,
            row.get("label") or Path(mount).name,
            row.get("name", ""),
            row.get("fstype", ""),
            "usb",
        )

    for device, mount, fstype in _read_proc_mounts():
        if fstype in NETWORK_FS:
            add_mount(mount, Path(mount).name, device, fstype, "network")
        elif mount.startswith("/media/") or mount.startswith("/run/media/"):
            add_mount(mount, Path(mount).name, device, fstype, "media")
        elif mount.startswith("/mnt/") and not mount.startswith("/mnt/music"):
            add_mount(mount, Path(mount).name, device, fstype, "mnt")

    for pattern in ("/media/*/*", "/media/*", "/run/media/*/*", "/run/media/*"):
        for p in Path("/").glob(pattern.lstrip("/")):
            try:
                mount = str(p.resolve())
            except OSError:
                mount = str(p)
            if mount in seen or _is_skip_mount(mount) or not p.is_dir():
                continue
            add_mount(mount, p.name, "", "", "media")

    return mounts


def audit_mount_files(mount_root: Path, rel_paths: list[str] | None = None) -> dict[str, Any]:
    """외장 마운트 음원 검수 — 파일 변경 없음 (robot-auditor 동일 규칙)."""
    wanted = {p.strip().lstrip("/") for p in (rel_paths or []) if p and str(p).strip()}
    items: list[dict[str, Any]] = []
    approved: list[str] = []
    rejected: list[str] = []
    audit_settings = load_audit_settings()

    for rel in _list_audio_rel_paths(mount_root, wanted if wanted else None):
        fp = mount_root / rel
        if not fp.is_file():
            continue
        audit = evaluate_audit_settings(fp, audit_settings)
        quality = evaluate_hires(fp)
        item = {
            "rel_path": rel,
            "verdict": "approved" if audit["pass"] else "rejected",
            "tier": quality.get("tier"),
            "reasons": audit.get("reasons") or [],
            "probe": audit.get("probe") or quality.get("probe"),
        }
        items.append(item)
        if audit["pass"]:
            approved.append(rel)
        else:
            rejected.append(rel)

    return {
        "mode": "audit_only",
        "files_modified": False,
        "robot": "robot-auditor",
        "mount_point": str(mount_root),
        "approved": len(approved),
        "rejected": len(rejected),
        "reviewed_files": approved,
        "rejected_files": rejected,
        "items": items,
    }


def scan_mount_file_list(mount_root: Path) -> dict[str, Any]:
    """수동 모드 — 곡 목록만 스캔 (검수·import 없음)."""
    files: list[dict[str, Any]] = []
    for rel in _list_audio_rel_paths(mount_root):
        fp = mount_root / rel
        try:
            st = fp.stat()
            size = st.st_size
        except OSError:
            size = 0
        files.append({"rel_path": rel, "size_bytes": size, "title": Path(rel).stem})
    return {
        "mount_point": str(mount_root),
        "files": files,
        "total": len(files),
    }


def _safe_batch_name(mount: Path) -> str:
    stamp = re.sub(r"[^a-zA-Z0-9_-]+", "_", mount.name)[:40] or "external"
    return f"external-{stamp}"


def _path_within_mount(path: Path, mount: Path) -> bool:
    try:
        path.resolve().relative_to(mount.resolve())
        return True
    except ValueError:
        return False


def stage_mount_files_to_incoming(
    mount_root: Path,
    rel_paths: list[str],
    incoming: Path,
) -> tuple[str, list[str]]:
    """외장 경로 → incoming/{batch}/ 복사. 반환: (batch_prefix, incoming_rel_paths)."""
    batch = _safe_batch_name(mount_root)
    incoming.mkdir(parents=True, exist_ok=True)
    staged: list[str] = []
    mount_resolved = mount_root.resolve()
    for rel in rel_paths:
        rel = str(rel or "").strip().lstrip("/")
        if not rel:
            continue
        src = mount_root / rel
        if src.is_symlink() or not _path_within_mount(src, mount_resolved):
            continue
        dest = incoming / batch / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            dest = incoming / batch / f"{src.stem}_{src.stat().st_mtime_ns}{src.suffix}"
        copy2(src, dest)
        staged.append(str(dest.relative_to(incoming)).replace("\\", "/"))
    return batch, staged


def import_staged_paths(incoming: Path, music_root: Path, incoming_rel_paths: list[str]) -> dict[str, Any]:
    return import_incoming_files(incoming, music_root, incoming_rel_paths)


def _load_state() -> dict[str, Any]:
    try:
        if STATE_PATH.is_file():
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_state(data: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def mark_mount_processed(mount_point: str) -> None:
    state = _load_state()
    done = set(state.get("processed_mounts") or [])
    done.add(mount_point)
    state["processed_mounts"] = sorted(done)
    _save_state(state)


def dismiss_mount(mount_point: str) -> None:
    state = _load_state()
    dismissed = set(state.get("dismissed_mounts") or [])
    dismissed.add(mount_point)
    state["dismissed_mounts"] = sorted(dismissed)
    state["pending_review"] = None
    _save_state(state)


def set_pending_review(payload: dict[str, Any] | None) -> None:
    state = _load_state()
    state["pending_review"] = payload
    _save_state(state)


def get_pending_review() -> dict[str, Any] | None:
    state = _load_state()
    pending = state.get("pending_review")
    if not pending:
        return None
    mount = pending.get("mount_point")
    if mount and not Path(mount).is_dir():
        state["pending_review"] = None
        _save_state(state)
        return None
    return pending


def process_external_library(
    mount_point: str,
    *,
    mode: str = "auto",
    paths: list[str] | None = None,
    import_rejected: list[str] | None = None,
    incoming: Path,
    music_root: Path,
) -> dict[str, Any]:
    """
    자동 모드: paths 생략 → 전체 검수, 통과분 즉시 import, 탈락은 pending_review.
    수동 모드: paths 지정 → 선택곡만 검수 후 동일.
    import_rejected: 탈락이어도 고객이 추가 선택한 rel_path.
    """
    mount_root = Path(mount_point).resolve()
    if not mount_root.is_dir():
        raise ValueError("mount_not_found")

    allowed = {m.mount_point for m in detect_external_mounts()}
    if mount_point not in allowed:
        raise ValueError("mount_not_allowed")

    rel_filter = [p.strip().lstrip("/") for p in (paths or []) if p and str(p).strip()]
    audit = audit_mount_files(mount_root, rel_filter if rel_filter else None)

    to_import = list(audit.get("reviewed_files") or [])
    override = [p.strip().lstrip("/") for p in (import_rejected or []) if p and str(p).strip()]
    rejected_set = set(audit.get("rejected_files") or [])
    for p in override:
        if p in rejected_set and p not in to_import:
            to_import.append(p)

    imported = {"moved": 0, "paths": []}
    if to_import:
        _, staged = stage_mount_files_to_incoming(mount_root, to_import, incoming)
        imported = import_staged_paths(incoming, music_root, staged)

    remaining_rejected = [p for p in audit.get("rejected_files") or [] if p not in override]
    review_payload = None
    if remaining_rejected:
        items_by_path = {it["rel_path"]: it for it in audit.get("items") or []}
        review_payload = {
            "mount_point": mount_point,
            "mode": mode,
            "rejected": [items_by_path[p] for p in remaining_rejected if p in items_by_path],
            "imported_count": imported.get("moved", 0),
            "detected_at": datetime.now(timezone.utc).isoformat(),
            "message": "검수 탈락 곡이 있습니다. 라이브러리에 추가할지 선택해 주세요.",
        }
        set_pending_review(review_payload)
    else:
        set_pending_review(None)
        mark_mount_processed(mount_point)

    return {
        "ok": True,
        "mode": mode,
        "audit": audit,
        "imported": imported,
        "pending_review": review_payload,
    }


# --- backward compat (usb_storage_watch) ---

def detect_usb_audio_mounts():
    return detect_external_mounts()


def get_usb_pending() -> dict[str, Any] | None:
    review = get_pending_review()
    if review:
        return {
            "mount_point": review.get("mount_point"),
            "label": Path(str(review.get("mount_point") or "")).name,
            "audio_files": len(review.get("rejected") or []),
            "message": review.get("message"),
            "mode": review.get("mode", "auto"),
            "rejected_items": review.get("rejected") or [],
        }
    mounts = detect_external_mounts()
    state = _load_state()
    dismissed = set(state.get("dismissed_mounts") or [])
    processed = set(state.get("processed_mounts") or [])
    for m in mounts:
        if m.mount_point in dismissed or m.mount_point in processed:
            continue
        return {
            "mount_point": m.mount_point,
            "label": m.label,
            "device": m.device,
            "audio_files": m.audio_files,
            "size_bytes": m.size_bytes,
            "source": m.source,
            "detected_at": datetime.now(timezone.utc).isoformat(),
            "message": "외장 스토리지가 연결되었습니다. 파일 탐색기에서 추가·복사·이동할 수 있습니다.",
            "mode": "detected",
        }
    return None


def refresh_usb_prompt_state() -> dict[str, Any] | None:
    return get_usb_pending()


def dismiss_usb_prompt(mount_point: str | None = None) -> None:
    mp = mount_point or (get_pending_review() or {}).get("mount_point")
    if mp:
        dismiss_mount(str(mp))


def mark_usb_imported(mount_point: str) -> None:
    mark_mount_processed(mount_point)


def import_usb_to_library(usb_mount: Path, music_root: Path, incoming: Path) -> dict[str, Any]:
    """레거시 — 전체 복사 대신 auto process 위임."""
    result = process_external_library(
        str(usb_mount),
        mode="auto",
        incoming=incoming,
        music_root=music_root,
    )
    return result.get("imported") or {"moved": 0, "paths": []}
