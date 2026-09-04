"""라이브러리 파일 탐색기 SSOT — music /media 루트 가상화 · mkdir/rename/delete/copy/move."""
from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path
from typing import Any, Literal

AUDIO_EXTS = {
    ".flac",
    ".wav",
    ".mp3",
    ".aac",
    ".m4a",
    ".ogg",
    ".opus",
    ".aiff",
    ".aif",
    ".alac",
    ".ape",
    ".wv",
    ".wma",
    ".dsf",
    ".dff",
}

RootName = Literal["music", "media"]

MUSIC_UI_ROOT = "music"
MEDIA_UI_ROOT = "/media"
# 내장 music 루트의 시스템 테스트음 — 탐색기 숨김 + 삭제/이동/이름변경 금지
PROTECTED_MUSIC_TOPDIRS = frozenset({"tones"})
SYSTEM_HIDDEN_NAMES = frozenset({
    "system volume information",
    "$recycle.bin",
    "lost+found",
    "imported",
})
COPY_SPACE_MARGIN_RATIO = float(os.getenv("WHICK_COPY_SPACE_MARGIN", "0.05"))
COPY_SPACE_MIN_FREE = int(os.getenv("WHICK_COPY_SPACE_MIN_FREE", str(1 << 30)))  # 1 GiB


class LibraryFsError(ValueError):
    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code
        self.message = message or code


def _is_protected_music_rel(rel: str | None) -> bool:
    """music 루트 바로 아래 tones/ 및 그 하위 경로."""
    parts = [p for p in _norm_rel(rel).split("/") if p]
    return bool(parts) and parts[0].lower() in PROTECTED_MUSIC_TOPDIRS


def _protected_music_error() -> LibraryFsError:
    return LibraryFsError(
        "protected",
        "시스템 테스트 폴더(tones)는 숨김·보호되어 삭제·변경할 수 없습니다",
    )

def music_real_root() -> Path:
    return Path(os.getenv("WHICK_MUSIC_DIR", "/var/lib/whick/library/music")).resolve()


def _norm_rel(path: str | None) -> str:
    raw = str(path or "").strip().replace("\\", "/")
    while raw.startswith("./"):
        raw = raw[2:]
    raw = raw.lstrip("/")
    if MUSIC_UI_ROOT == raw or raw.startswith(MUSIC_UI_ROOT + "/"):
        raw = raw[len(MUSIC_UI_ROOT) :].lstrip("/")
    if raw.startswith("media/"):
        raw = raw[len("media/") :]
    parts = [p for p in raw.split("/") if p and p != "."]
    if any(p == ".." for p in parts):
        raise LibraryFsError("path_escape", "상위 경로로 이동할 수 없습니다")
    return "/".join(parts)


def _ensure_within(path: Path, root: Path) -> Path:
    resolved = path.resolve()
    root_res = root.resolve()
    try:
        resolved.relative_to(root_res)
    except ValueError as exc:
        raise LibraryFsError("path_escape", "허용되지 않은 경로") from exc
    return resolved


def resolve_media_real(rel: str) -> Path:
    """UI /media 상대경로 → 실제 /media 또는 /run/media 경로."""
    rel = _norm_rel(rel)
    if not rel:
        # 가상 루트 — 실체는 /media (없으면 /run/media 목록용 센티널)
        media = Path("/media")
        if media.is_dir():
            return media.resolve()
        run = Path("/run/media")
        if run.is_dir():
            return run.resolve()
        media.mkdir(parents=True, exist_ok=True)
        return media.resolve()

    candidates: list[Path] = [Path("/media") / rel]
    run = Path("/run/media")
    if run.is_dir():
        # /run/media/<user>/<label>/...
        first = rel.split("/", 1)[0]
        rest = rel.split("/", 1)[1] if "/" in rel else ""
        for user_dir in run.iterdir():
            if not user_dir.is_dir():
                continue
            label = user_dir / first
            if rest:
                candidates.append(label / rest)
            else:
                candidates.append(label)
            # /run/media/<user>/rel...
            candidates.append(user_dir / rel)

    for c in candidates:
        try:
            if c.exists():
                # 허용 루트 검증
                rp = c.resolve()
                ok = False
                for base in (Path("/media"), Path("/run/media")):
                    if base.is_dir():
                        try:
                            rp.relative_to(base.resolve())
                            ok = True
                            break
                        except ValueError:
                            continue
                if ok:
                    return rp
        except OSError:
            continue

    # 생성·쓰기용 기본: /media/<rel>
    target = Path("/media") / rel
    parent = target.parent
    if parent == Path("/media") or str(parent).startswith("/media/"):
        return target
    raise LibraryFsError("not_found", "경로 없음")


def resolve_path(root: RootName, rel: str | None = "") -> Path:
    rel_n = _norm_rel(rel)
    if root == "music":
        base = music_real_root()
        base.mkdir(parents=True, exist_ok=True)
        if not rel_n:
            return base
        return _ensure_within((base / rel_n), base)
    if root == "media":
        return resolve_media_real(rel_n)
    raise LibraryFsError("bad_root", "root must be music or media")


def to_ui_path(root: RootName, real: Path) -> str:
    if root == "music":
        base = music_real_root()
        try:
            rel = real.resolve().relative_to(base)
            s = str(rel).replace("\\", "/")
            return MUSIC_UI_ROOT if s in (".", "") else f"{MUSIC_UI_ROOT}/{s}"
        except ValueError:
            return MUSIC_UI_ROOT
    # media
    rp = real.resolve()
    for base in (Path("/media"), Path("/run/media")):
        if not base.is_dir():
            continue
        try:
            rel = rp.relative_to(base.resolve())
            parts = list(rel.parts)
            # /run/media/<user>/<label> → UI /media/<label>/...
            if str(base) == "/run/media" and len(parts) >= 1:
                # drop user component when present
                if len(parts) >= 2:
                    parts = parts[1:]
            s = "/".join(parts)
            return MEDIA_UI_ROOT if not s else f"{MEDIA_UI_ROOT}/{s}"
        except ValueError:
            continue
    return MEDIA_UI_ROOT


def free_bytes_for(path: Path) -> int:
    try:
        target = path if path.is_dir() else path.parent
        st = os.statvfs(target)
        return int(st.f_bavail * st.f_frsize)
    except OSError:
        return 0


def path_size_bytes(path: Path) -> int:
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    total = 0
    try:
        for dirpath, _, filenames in os.walk(path):
            for name in filenames:
                fp = Path(dirpath) / name
                try:
                    total += fp.stat().st_size
                except OSError:
                    pass
    except OSError:
        pass
    return total


def list_dir(root: RootName, rel: str | None = "") -> dict[str, Any]:
    rel_n = _norm_rel(rel)
    entries: list[dict[str, Any]] = []
    seen_names: set[str] = set()

    if root == "media" and not rel_n:
        # /media 루트: /media/* + /run/media/*/*
        for base_glob in (Path("/media").glob("*"),):
            for p in sorted(base_glob, key=lambda x: x.name.lower()):
                if not p.is_dir() and not p.is_file():
                    continue
                if p.name.lower() in SYSTEM_HIDDEN_NAMES or p.name.startswith("."):
                    continue
                if p.name in seen_names:
                    continue
                seen_names.add(p.name)
                entries.append(_entry_dict("media", p, p.name))
        run = Path("/run/media")
        if run.is_dir():
            for user_dir in sorted(run.iterdir(), key=lambda x: x.name.lower()):
                if not user_dir.is_dir():
                    continue
                for p in sorted(user_dir.iterdir(), key=lambda x: x.name.lower()):
                    if p.name in seen_names:
                        continue
                    if not p.is_dir() and not p.is_file():
                        continue
                    if p.name.lower() in SYSTEM_HIDDEN_NAMES or p.name.startswith("."):
                        continue
                    seen_names.add(p.name)
                    entries.append(_entry_dict("media", p, p.name))
        return {
            "root": root,
            "path": MEDIA_UI_ROOT,
            "parent": None,
            "entries": entries,
            "free_bytes": free_bytes_for(Path("/media") if Path("/media").is_dir() else Path("/")),
        }

    real = resolve_path(root, rel_n)
    if not real.is_dir():
        raise LibraryFsError("not_a_dir", "폴더가 아닙니다")
    if root == "music" and _is_protected_music_rel(rel_n):
        raise _protected_music_error()
    try:
        children = sorted(real.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
    except OSError as exc:
        raise LibraryFsError("list_failed", str(exc)) from exc

    for p in children:
        name = p.name
        if name.startswith("."):
            continue
        lower_name = name.lower()
        if lower_name in SYSTEM_HIDDEN_NAMES:
            continue
        # 내장 루트 tones 폴더 숨김 (테스트용 시스템 음원)
        if root == "music" and not rel_n and lower_name in PROTECTED_MUSIC_TOPDIRS:
            continue
        entries.append(_entry_dict(root, p, name))

    ui = to_ui_path(root, real)
    parent = None
    if rel_n:
        parent_rel = "/".join(rel_n.split("/")[:-1])
        parent = to_ui_path(root, resolve_path(root, parent_rel))

    return {
        "root": root,
        "path": ui,
        "parent": parent,
        "entries": entries,
        "free_bytes": free_bytes_for(real),
    }


def _entry_dict(root: RootName, real: Path, name: str) -> dict[str, Any]:
    is_dir = real.is_dir()
    size = 0 if is_dir else path_size_bytes(real)
    ext = real.suffix.lower() if real.is_file() else ""
    return {
        "name": name,
        "path": to_ui_path(root, real),
        "type": "dir" if is_dir else "file",
        "size_bytes": size,
        "is_audio": (not is_dir) and ext in AUDIO_EXTS,
        "ext": ext.lstrip("."),
    }


def mkdir(root: RootName, parent_rel: str, name: str) -> dict[str, Any]:
    name = str(name or "").strip()
    if not name or "/" in name or name in (".", ".."):
        raise LibraryFsError("bad_name", "잘못된 폴더 이름")
    if root == "music" and not _norm_rel(parent_rel) and name.lower() in PROTECTED_MUSIC_TOPDIRS:
        raise LibraryFsError("protected", "시스템 예약 폴더 이름(tones)은 사용할 수 없습니다")
    parent = resolve_path(root, parent_rel)
    if not parent.is_dir():
        raise LibraryFsError("not_a_dir", "부모 폴더 없음")
    dest = parent / name
    if dest.exists():
        raise LibraryFsError("exists", "이미 존재하는 이름")
    dest.mkdir(parents=False, exist_ok=False)
    return {"ok": True, "path": to_ui_path(root, dest)}


def rename(root: RootName, rel: str, new_name: str) -> dict[str, Any]:
    new_name = str(new_name or "").strip()
    if not new_name or "/" in new_name or new_name in (".", ".."):
        raise LibraryFsError("bad_name", "잘못된 이름")
    rel_n = _norm_rel(rel)
    if not rel_n:
        raise LibraryFsError("root_locked", "루트는 이름을 바꿀 수 없습니다")
    if root == "music" and _is_protected_music_rel(rel_n):
        raise _protected_music_error()
    if root == "music" and new_name.lower() in PROTECTED_MUSIC_TOPDIRS and "/" not in rel_n:
        raise LibraryFsError("protected", "시스템 예약 폴더 이름(tones)은 사용할 수 없습니다")
    src = resolve_path(root, rel_n)
    if not src.exists():
        raise LibraryFsError("not_found", "대상 없음")
    old_ui = to_ui_path(root, src)
    old_real = str(src.resolve())
    dest = src.parent / new_name
    if dest.exists():
        raise LibraryFsError("exists", "이미 존재하는 이름")
    src.rename(dest)
    new_real = str(dest.resolve())
    return {
        "ok": True,
        "path": to_ui_path(root, dest),
        "old_path": old_ui,
        "old_real": old_real,
        "new_real": new_real,
    }


def delete_paths(root: RootName, rels: list[str]) -> dict[str, Any]:
    deleted: list[str] = []
    deleted_real: list[str] = []
    errors: list[dict[str, str]] = []
    for rel in rels:
        rel_n = _norm_rel(rel)
        if not rel_n:
            errors.append({"path": rel, "error": "root_locked"})
            continue
        if root == "music" and _is_protected_music_rel(rel_n):
            errors.append({"path": rel, "error": "protected"})
            continue
        try:
            target = resolve_path(root, rel_n)
            if not target.exists():
                errors.append({"path": rel, "error": "not_found"})
                continue
            ui = to_ui_path(root, target)
            real = str(target.resolve())
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
            deleted.append(ui)
            deleted_real.append(real)
        except LibraryFsError as exc:
            errors.append({"path": rel, "error": exc.code})
        except OSError as exc:
            errors.append({"path": rel, "error": str(exc)})
    return {"ok": True, "deleted": deleted, "deleted_real": deleted_real, "errors": errors}


def _unique_dest(dest_dir: Path, name: str) -> Path:
    candidate = dest_dir / name
    if not candidate.exists():
        return candidate
    stem = Path(name).stem
    suffix = Path(name).suffix
    for i in range(1, 1000):
        alt = dest_dir / f"{stem} ({i}){suffix}"
        if not alt.exists():
            return alt
    return dest_dir / f"{stem}_{uuid.uuid4().hex[:8]}{suffix}"


def preflight_copy(
    sources: list[dict[str, str]],
    dest_root: RootName,
    dest_rel: str,
) -> dict[str, Any]:
    dest_dir = resolve_path(dest_root, dest_rel)
    if not dest_dir.is_dir():
        raise LibraryFsError("not_a_dir", "대상 폴더 없음")
    need = 0
    resolved_sources: list[Path] = []
    for item in sources:
        r = str(item.get("root") or "").strip()
        p = str(item.get("path") or "").strip()
        if r not in ("music", "media"):
            raise LibraryFsError("bad_root", "source root invalid")
        src = resolve_path(r, p)  # type: ignore[arg-type]
        if not src.exists():
            raise LibraryFsError("not_found", f"원본 없음: {p}")
        need += path_size_bytes(src)
        resolved_sources.append(src)
    free = free_bytes_for(dest_dir)
    margin = max(int(need * COPY_SPACE_MARGIN_RATIO), COPY_SPACE_MIN_FREE if need > 0 else 0)
    ok = free >= (need + margin) if need > 0 else True
    return {
        "ok": ok,
        "need_bytes": need,
        "free_bytes": free,
        "margin_bytes": margin,
        "dest": to_ui_path(dest_root, dest_dir),
        "source_count": len(resolved_sources),
    }


def copy_or_move(
    sources: list[dict[str, str]],
    dest_root: RootName,
    dest_rel: str,
    *,
    move: bool = False,
) -> dict[str, Any]:
    check = preflight_copy(sources, dest_root, dest_rel)
    if not check["ok"]:
        raise LibraryFsError(
            "no_space",
            f"공간 부족 — 필요 {check['need_bytes']} / 남음 {check['free_bytes']}",
        )
    dest_dir = resolve_path(dest_root, dest_rel)
    if not dest_dir.is_dir():
        raise LibraryFsError("not_a_dir", "대상 폴더 없음")
    # /media 루트에 직접 붙이지 말고, 꽂힌 볼륨(하위 폴더)을 연 뒤 붙여넣기
    if dest_root == "media" and not _norm_rel(dest_rel):
        raise LibraryFsError(
            "pick_volume",
            "외장 볼륨 폴더(/media/장치명)를 연 다음 붙여넣기 하세요",
        )

    results: list[dict[str, Any]] = []
    for item in sources:
        r = str(item.get("root") or "").strip()
        p = str(item.get("path") or "").strip()
        if r == "music" and _is_protected_music_rel(p) and move:
            results.append({"path": p, "error": "protected"})
            continue
        src = resolve_path(r, p)  # type: ignore[arg-type]
        if not src.exists():
            results.append({"path": p, "error": "not_found"})
            continue
        # 자기 자신/하위로 복사 방지
        try:
            if dest_dir.resolve() == src.resolve() or str(dest_dir.resolve()).startswith(
                str(src.resolve()) + os.sep
            ):
                results.append({"path": p, "error": "into_self"})
                continue
        except OSError:
            pass
        # tones 폴더 안으로의 붙여넣기도 금지
        if dest_root == "music" and _is_protected_music_rel(dest_rel):
            results.append({"path": p, "error": "protected"})
            continue
        dest = _unique_dest(dest_dir, src.name)
        from_ui = to_ui_path(r, src)  # type: ignore[arg-type]
        old_real = str(src.resolve())
        try:
            if move:
                shutil.move(str(src), str(dest))
            elif src.is_dir():
                shutil.copytree(src, dest)
            else:
                shutil.copy2(src, dest)
            results.append(
                {
                    "from": from_ui,
                    "to": to_ui_path(dest_root, dest),
                    "from_real": old_real,
                    "to_real": str(dest.resolve()),
                    "moved": move,
                }
            )
        except OSError as exc:
            if getattr(exc, "errno", None) == 28:
                raise LibraryFsError("no_space", "디스크 공간 부족") from exc
            results.append({"path": p, "error": str(exc)})

    return {"ok": True, "results": results, "preflight": check}


def collect_audio_under(root: RootName, rels: list[str]) -> list[Path]:
    """선택 경로(파일·폴더) 아래 음원 실경로 목록."""
    out: list[Path] = []
    seen: set[str] = set()
    for rel in rels:
        try:
            target = resolve_path(root, rel)
        except LibraryFsError:
            continue
        if not target.exists():
            continue
        files: list[Path] = []
        if target.is_file():
            if target.suffix.lower() in AUDIO_EXTS:
                files = [target]
        else:
            for dirpath, _, filenames in os.walk(target):
                for name in filenames:
                    fp = Path(dirpath) / name
                    if fp.suffix.lower() in AUDIO_EXTS:
                        files.append(fp)
        for fp in files:
            key = str(fp.resolve())
            if key in seen:
                continue
            seen.add(key)
            out.append(fp.resolve())
    return out


def is_under_media(path: Path) -> bool:
    ps = str(path.resolve())
    return ps.startswith("/media/") or ps.startswith("/run/media/") or ps in ("/media", "/run/media")


def is_under_music(path: Path) -> bool:
    try:
        path.resolve().relative_to(music_real_root())
        return True
    except ValueError:
        return False
