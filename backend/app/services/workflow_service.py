"""작업 폴더(D:\\YouTubeMusic) 단계별 워크플로."""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AppSetting, Song
from app.services.pipeline_defaults import (
    DEFAULT_PIPELINE_CONFIG,
    LEGACY_STAGE_FOLDERS,
    WORKFLOW_STAGES,
    get_default_config,
)

WORK_ROOT_KEY = "pipeline_work_root"
PIPELINE_CONFIG_KEY = "pipeline_config_json"

AUDIO_EXT = {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
TEXT_EXT = {".txt", ".md", ".srt", ".ass", ".json"}


def _stage_map() -> dict[str, dict]:
    return {s["id"]: s for s in WORKFLOW_STAGES}


def _stage_by_folder(folder_name: str) -> dict | None:
    for s in WORKFLOW_STAGES:
        if s["folder"] == folder_name:
            return s
    return None


async def get_work_root(db: AsyncSession) -> Path:
    row = await db.get(AppSetting, WORK_ROOT_KEY)
    root = row.value if row and row.value else DEFAULT_PIPELINE_CONFIG["work_root"]
    return Path(root)


async def set_work_root(db: AsyncSession, path: str) -> Path:
    root = Path(path)
    result = await db.execute(select(AppSetting).where(AppSetting.key == WORK_ROOT_KEY))
    row = result.scalar_one_or_none()
    if row:
        row.value = str(root)
    else:
        db.add(AppSetting(key=WORK_ROOT_KEY, value=str(root)))
    await db.flush()
    return root


async def get_pipeline_config(db: AsyncSession) -> dict:
    result = await db.execute(select(AppSetting).where(AppSetting.key == PIPELINE_CONFIG_KEY))
    row = result.scalar_one_or_none()
    if not row or not row.value:
        cfg = get_default_config()
        cfg["work_root"] = str(await get_work_root(db))
        return cfg
    cfg = json.loads(row.value)
    merged = get_default_config()
    for key, val in cfg.items():
        if isinstance(val, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **val}
        else:
            merged[key] = val
    merged["work_root"] = str(await get_work_root(db))
    return merged


async def save_pipeline_config(db: AsyncSession, updates: dict) -> dict:
    current = await get_pipeline_config(db)
    if "work_root" in updates:
        await set_work_root(db, updates.pop("work_root"))
    for key, val in updates.items():
        if isinstance(val, dict) and key in current and isinstance(current[key], dict):
            current[key] = {**current[key], **val}
        else:
            current[key] = val
    current["work_root"] = str(await get_work_root(db))
    stored = {k: v for k, v in current.items() if k != "work_root"}
    result = await db.execute(select(AppSetting).where(AppSetting.key == PIPELINE_CONFIG_KEY))
    row = result.scalar_one_or_none()
    payload = json.dumps(stored, ensure_ascii=False)
    if row:
        row.value = payload
    else:
        db.add(AppSetting(key=PIPELINE_CONFIG_KEY, value=payload))
    await db.flush()
    return current


def resolve_safe_path(root: Path, relative: str) -> Path:
    rel = relative.replace("\\", "/").strip("/")
    target = (root / rel).resolve()
    root_resolved = root.resolve()
    if not str(target).startswith(str(root_resolved)):
        raise ValueError("허용되지 않은 경로입니다")
    return target


async def init_work_folders(db: AsyncSession) -> dict:
    root = await get_work_root(db)
    root.mkdir(parents=True, exist_ok=True)
    stage_map = _stage_map()
    current_folders = {s["folder"] for s in WORKFLOW_STAGES}

    created: list[str] = []
    for stage in WORKFLOW_STAGES:
        path = root / stage["folder"]
        if not path.exists():
            path.mkdir(parents=True)
            created.append(str(path))
        readme = path / "_README.txt"
        readme.write_text(
            f"{stage['label']}\n{stage['description']}\n",
            encoding="utf-8",
        )

    migrated: list[dict[str, str]] = []
    removed_legacy: list[str] = []
    legacy_remaining: list[str] = []

    for legacy_name, target_id in LEGACY_STAGE_FOLDERS.items():
        legacy_dir = root / legacy_name
        if not legacy_dir.is_dir():
            continue
        if legacy_name in current_folders:
            continue

        target_stage = stage_map.get(target_id)
        if not target_stage:
            continue
        dest_parent = root / target_stage["folder"]

        for item in sorted(legacy_dir.iterdir(), key=lambda p: p.name.lower()):
            if not item.is_dir() or item.name.startswith("_"):
                continue
            try:
                dest = move_project(item, dest_parent)
                migrated.append({"from": str(item), "to": str(dest)})
            except FileNotFoundError:
                continue

        if _legacy_dir_removable(legacy_dir):
            shutil.rmtree(legacy_dir)
            removed_legacy.append(legacy_name)
        else:
            legacy_remaining.append(legacy_name)

    return {
        "created": created,
        "migrated": migrated,
        "removed_legacy": removed_legacy,
        "legacy_remaining": legacy_remaining,
    }


def _legacy_dir_removable(path: Path) -> bool:
    if not path.is_dir():
        return False
    for item in path.iterdir():
        if item.name.startswith(".") or item.name == "_README.txt":
            continue
        return False
    return True


def _has_project_markers(folder: Path) -> bool:
    """곡 프로젝트 폴더인지 (audio / title / lyrics 등)."""
    if not folder.is_dir():
        return False
    for f in folder.iterdir():
        if not f.is_file():
            continue
        name = f.name.lower()
        if name.startswith("audio.") or name in {
            "title.txt",
            "lyrics_en.txt",
            "lyrics_ko.txt",
            "suno_prompt.txt",
        }:
            return True
    return False


def _count_stage_projects(stage_folder: Path) -> int:
    """단계 안 곡 프로젝트 수: 앨범/트랙 또는 예전 평면 구조."""
    if not stage_folder.exists():
        return 0
    count = 0
    for item in stage_folder.iterdir():
        if not item.is_dir() or item.name.startswith("_") or item.name.startswith("."):
            continue
        nested = [
            c
            for c in item.iterdir()
            if c.is_dir() and not c.name.startswith(".") and not c.name.startswith("_")
        ]
        if nested:
            count += len(nested)
        elif _has_project_markers(item):
            count += 1
    return count


def list_stages(root: Path) -> list[dict]:
    items = []
    for stage in WORKFLOW_STAGES:
        folder = root / stage["folder"]
        count = _count_stage_projects(folder)
        items.append({**stage, "path": str(folder), "project_count": count})
    return items


def browse_directory(path: Path, *, work_root: Path | None = None) -> dict:
    if not path.exists():
        raise FileNotFoundError("폴더가 없습니다")
    if not path.is_dir():
        raise ValueError("폴더가 아닙니다")

    stage_folders = {s["folder"] for s in WORKFLOW_STAGES}
    at_work_root = work_root is not None and path.resolve() == work_root.resolve()

    # work_root 기준: stage 바로 아래=0, 앨범 안=1 …
    depth_under_stage = None
    if work_root is not None:
        try:
            rel_parts = path.resolve().relative_to(work_root.resolve()).parts
            if rel_parts and rel_parts[0] in stage_folders:
                depth_under_stage = len(rel_parts) - 1
        except ValueError:
            depth_under_stage = None

    entries = []
    for item in sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        if item.name.startswith(".") or item.name == "_README.txt":
            continue
        if item.name.startswith(REVIEW_WIP_PREFIX):
            continue
        if at_work_root and item.is_dir() and item.name not in stage_folders:
            continue
        stat = item.stat()
        entry = {
            "name": item.name,
            "path": str(item),
            "is_dir": item.is_dir(),
            "size": stat.st_size if item.is_file() else None,
            "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        }
        if item.is_file():
            ext = item.suffix.lower()
            entry["kind"] = (
                "audio" if ext in AUDIO_EXT else "image" if ext in IMAGE_EXT else "text" if ext in TEXT_EXT else "file"
            )
        else:
            if depth_under_stage == 0:
                entry["kind"] = "project" if _has_project_markers(item) else "album"
            elif depth_under_stage == 1:
                entry["kind"] = "project"
            else:
                entry["kind"] = "folder"
        entries.append(entry)
    return {"path": str(path), "entries": entries}


def _album_root_for_project(project_dir: Path) -> Path:
    """트랙이 앨범 하위에 있으면 앨범 폴더, 단계 바로 아래면 트랙 자신."""
    parent = project_dir.parent
    stage_names = {s["folder"] for s in WORKFLOW_STAGES} | set(LEGACY_STAGE_FOLDERS)
    if parent.name in stage_names:
        return project_dir
    return parent if parent.is_dir() else project_dir


def collect_album_images(project_dir: Path) -> list[dict[str, str]]:
    """앨범 폴더(상위)와 그 안 트랙 폴더의 이미지 목록."""
    album = _album_root_for_project(project_dir)
    if not album.is_dir():
        album = project_dir
    seen: set[str] = set()
    out: list[dict[str, str]] = []

    def add_file(f: Path) -> None:
        if not f.is_file() or f.suffix.lower() not in IMAGE_EXT:
            return
        try:
            key = str(f.resolve())
        except OSError:
            key = str(f)
        if key in seen:
            return
        seen.add(key)
        try:
            rel = f.resolve().relative_to(album.resolve()).as_posix()
        except ValueError:
            rel = f.name
        folder = f.parent.name
        if f.parent.resolve() == album.resolve():
            label = f.name
            folder = album.name
        else:
            label = f"{folder} / {f.name}"
        out.append({"path": str(f), "label": label, "folder": folder, "name": f.name, "rel": rel})

    if album.is_dir():
        for f in sorted(album.iterdir(), key=lambda p: p.name.lower()):
            if f.is_file():
                add_file(f)
        for d in sorted([p for p in album.iterdir() if p.is_dir()], key=lambda p: p.name.lower()):
            for f in sorted(d.rglob("*"), key=lambda p: str(p).lower()):
                add_file(f)
    else:
        for f in sorted(project_dir.rglob("*"), key=lambda p: str(p).lower()):
            add_file(f)

    out.sort(key=lambda it: (_cover_image_sort_key(it["path"]), it["folder"].lower(), it["name"].lower()))
    return out


def find_project_assets(project_dir: Path) -> dict:
    audio: list[str] = []
    images: list[str] = []
    lyrics_en = lyrics_ko = track_title = None

    for f in sorted(project_dir.rglob("*")):
        if not f.is_file():
            continue
        ext = f.suffix.lower()
        name_lower = f.name.lower()
        if ext in AUDIO_EXT and not audio:
            audio.append(str(f))
        elif ext in IMAGE_EXT:
            images.append(str(f))
        elif ext in TEXT_EXT or ext == ".json":
            if "lyrics_ko" in name_lower or "가사" in f.name and "en" not in name_lower:
                lyrics_ko = f.read_text(encoding="utf-8", errors="ignore")
            elif "lyrics_en" in name_lower or "english" in name_lower:
                lyrics_en = f.read_text(encoding="utf-8", errors="ignore")
            elif name_lower == "lyrics.txt":
                lyrics_en = f.read_text(encoding="utf-8", errors="ignore")
            elif name_lower == "title.txt":
                track_title = f.read_text(encoding="utf-8", errors="ignore").strip()

    images.sort(key=lambda p: (_cover_image_sort_key(p), Path(p).name.lower()))

    if not track_title:
        track_title = project_dir.name

    return {
        "audio_paths": audio,
        "image_paths": images,
        "cover_image_paths": [p for p in images if not _is_generated_thumbnail(p)],
        "album_images": collect_album_images(project_dir),
        "lyrics_en": lyrics_en,
        "lyrics_ko": lyrics_ko,
        "track_title": track_title,
    }


def _is_generated_thumbnail(path: str | Path) -> bool:
    """업로드용으로 저장한 thumbnail.jpg — 커버 원본이 아님."""
    return Path(path).name.lower() == "thumbnail.jpg"


def pick_track_cover(assets: dict) -> Path | None:
    """곡 영상 배경용 커버. 유튜브 목록용 thumbnail.jpg는 제외."""
    covers = assets.get("cover_image_paths") or [
        p for p in (assets.get("image_paths") or []) if not _is_generated_thumbnail(p)
    ]
    if covers:
        return Path(covers[0])
    return None


def pick_album_fallback_cover(project_dirs: list[Path]) -> Path | None:
    """곡 커버가 없을 때 쓸 앨범 메인 이미지 (저장한 thumbnail.jpg 또는 앨범 폴더 그림)."""
    if not project_dirs:
        return None
    ordered: list[Path] = []
    first = project_dirs[0]
    thumb = first / "thumbnail.jpg"
    if thumb.is_file():
        ordered.append(thumb)
    album = _album_root_for_project(first)
    if album.is_dir():
        album_thumb = album / "thumbnail.jpg"
        if album_thumb.is_file():
            ordered.append(album_thumb)
        for f in sorted(album.iterdir(), key=lambda p: p.name.lower()):
            if f.is_file() and f.suffix.lower() in IMAGE_EXT:
                ordered.append(f)
    for d in project_dirs:
        assets = find_project_assets(d)
        cover = pick_track_cover(assets)
        if cover:
            ordered.append(cover)
        t = d / "thumbnail.jpg"
        if t.is_file():
            ordered.append(t)
    seen: set[str] = set()
    unique: list[Path] = []
    for p in ordered:
        try:
            key = str(p.resolve())
        except OSError:
            key = str(p)
        if key in seen or not p.is_file():
            continue
        seen.add(key)
        unique.append(p)
    if not unique:
        return None
    real = [p for p in unique if not _is_generated_thumbnail(p)]
    # 메인은 저장한 앨범 썸네일을 우선
    for p in unique:
        if _is_generated_thumbnail(p):
            return p
    return real[0] if real else unique[0]


LAST_PIPELINE_MARKER = "last_pipeline_output.json"


def remember_pipeline_output(project_dir: Path, video_path: Path, extra: dict | None = None) -> None:
    payload = {"video": str(video_path), **(extra or {})}
    (project_dir / LAST_PIPELINE_MARKER).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_last_pipeline_video(project_dir: Path) -> Path | None:
    marker = project_dir / LAST_PIPELINE_MARKER
    if not marker.is_file():
        return None
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    p = Path(str(data.get("video") or ""))
    return p if p.is_file() else None


def album_name_from_projects(project_paths: list[Path | str]) -> str:
    """합본 출력명 — 곡 폴더의 상위(앨범) 폴더. 스테이지 폴더는 제외."""
    if not project_paths:
        return ""
    first = Path(project_paths[0])
    parent = first.parent
    stage_names = {s["folder"] for s in WORKFLOW_STAGES} | set(LEGACY_STAGE_FOLDERS)
    if parent.name in stage_names:
        return ""
    return parent.name.strip()


def resolve_playlist_output_title(project_paths: list[str], hint: str | None = None) -> str:
    """mp4·검수 폴더 이름. 업로드 제목과 별개로 앨범 폴더명을 쓴다."""
    album = album_name_from_projects(project_paths)
    if album:
        return album
    hint = (hint or "").strip()
    if hint:
        return hint
    if project_paths:
        return Path(project_paths[0]).name
    return "Playlist"


REVIEW_WIP_PREFIX = "_작업중_"
_REVIEW_STAMP_RE = re.compile(r"^\d{8}_\d{4,6}_")


def sanitize_review_folder_name(title: str) -> str:
    raw = (title or "").strip() or "Playlist"
    safe = "".join(
        c if (c.isalnum() or c in " _-") or ("가" <= c <= "힣") else "_"
        for c in raw
    )
    return safe[:60].strip() or "Playlist"


def _review_album_key(folder_name: str) -> str:
    name = folder_name
    if name.startswith(REVIEW_WIP_PREFIX):
        name = name[len(REVIEW_WIP_PREFIX) :]
    name = _REVIEW_STAMP_RE.sub("", name)
    if name.endswith("_output"):
        name = name[: -len("_output")]
    return name.strip()


def discard_review_work_dir(path: Path) -> None:
    """실패한·미완성 작업 폴더 삭제."""
    try:
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
    except OSError:
        pass


def publish_review_output(work_dir: Path, review_root: Path, final_name: str) -> Path:
    """완성본만 검수대기에 남김. 같은 앨범의 이전·중간 폴더는 지움."""
    review_root.mkdir(parents=True, exist_ok=True)
    dest = review_root / final_name
    key = _review_album_key(final_name)
    for item in list(review_root.iterdir()) if review_root.is_dir() else []:
        if not item.is_dir():
            continue
        if item.resolve() == work_dir.resolve():
            continue
        if _review_album_key(item.name) == key:
            shutil.rmtree(item, ignore_errors=True)
    if dest.exists() and dest.resolve() != work_dir.resolve():
        shutil.rmtree(dest, ignore_errors=True)
    if work_dir.resolve() != dest.resolve():
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        shutil.move(str(work_dir), str(dest))
    return dest


def _cover_image_sort_key(path: str) -> int:
    name = Path(path).name.lower()
    if name == "thumbnail.jpg":
        return 9  # 생성본은 맨 뒤
    if name.startswith(("cover.", "artwork.", "album.", "image.")):
        return 0
    if name.startswith("thumbnail."):  # thumbnail.jpeg 등 원본
        return 1
    return 2


def pipeline_relative_path(root: Path, project_dir: Path) -> str:
    return str(project_dir.resolve().relative_to(root.resolve())).replace("\\", "/")


def _sanitize_folder_title(title: str) -> str:
    for ch in '/\\:*?"<>|':
        title = title.replace(ch, "-")
    return title.strip(". ") or "untitled"


def album_pipeline_folder_name(album) -> str:
    """작업폴더 안 앨범 폴더명 (예: A Little Something)."""
    title = str(getattr(album, "title", None) or album.get("title") or "").strip()
    return _sanitize_folder_title(title)


def song_display_title(song, language: str = "en") -> str:
    """폴더명·title.txt용 표시 제목."""
    lang = (language or "en").lower()
    if lang == "en":
        title = str(getattr(song, "title_en", None) or song.get("title_en") or "").strip()
        if not title:
            title = str(getattr(song, "title", None) or song.get("title") or "").strip()
    else:
        title = str(getattr(song, "title", None) or song.get("title") or "").strip()
    return _sanitize_folder_title(title)


def build_pipeline_project_name(song, language: str = "en") -> str:
    """곡 프로젝트명: 01 Before I Open My Eyes 형식."""
    track_number = int(getattr(song, "track_number", None) or song.get("track_number") or 1)
    title = song_display_title(song, language)
    return f"{track_number:02d} {title}"


def ensure_album_work_folder(root: Path, album, stage_id: str = "music") -> Path:
    """01_음악작업/<앨범제목>/ 폴더 생성."""
    stage = _stage_map().get(stage_id)
    if not stage:
        raise ValueError("알 수 없는 단계입니다")
    album_dir = root / stage["folder"] / album_pipeline_folder_name(album)
    album_dir.mkdir(parents=True, exist_ok=True)
    return album_dir


def remove_pipeline_project(root: Path, relative: str | None) -> bool:
    if not relative or not relative.strip():
        return False
    stage_folders = {s["folder"] for s in WORKFLOW_STAGES}
    top = Path(relative.replace("\\", "/")).parts[0] if relative else ""
    if top not in stage_folders:
        return False
    try:
        target = resolve_safe_path(root, relative)
    except ValueError:
        return False
    if not target.is_dir():
        return False
    shutil.rmtree(target)
    # 앨범 폴더가 비면 제거
    parent = target.parent
    stage_dirs = {root / s["folder"] for s in WORKFLOW_STAGES}
    if parent not in stage_dirs and parent.is_dir():
        leftover = [
            p for p in parent.iterdir()
            if not p.name.startswith(".") and p.name != "_README.txt"
        ]
        if not leftover:
            try:
                parent.rmdir()
            except OSError:
                pass
    return True


async def is_pipeline_path_in_use(
    db: AsyncSession,
    pipeline_path: str | None,
    exclude_song_ids: set[int] | None = None,
) -> bool:
    if not pipeline_path or not pipeline_path.strip():
        return False
    query = select(Song.id).where(Song.pipeline_path == pipeline_path)
    if exclude_song_ids:
        query = query.where(Song.id.not_in(exclude_song_ids))
    result = await db.execute(query.limit(1))
    return result.scalar_one_or_none() is not None


async def remove_pipeline_project_if_unused(
    db: AsyncSession,
    root: Path,
    pipeline_path: str | None,
    exclude_song_ids: set[int] | None = None,
) -> bool:
    if not pipeline_path:
        return False
    if await is_pipeline_path_in_use(db, pipeline_path, exclude_song_ids):
        return False
    return remove_pipeline_project(root, pipeline_path)


def _clear_export_artifacts(dest: Path) -> None:
    if not dest.is_dir():
        return
    for item in dest.iterdir():
        name = item.name.lower()
        if item.is_file() and (
            name.startswith("audio.")
            or name.startswith("thumbnail.")
            or name in {"lyrics_en.txt", "lyrics_ko.txt", "suno_prompt.txt", "title.txt"}
        ):
            item.unlink()


def move_project(src: Path, dest_parent: Path, new_name: str | None = None) -> Path:
    if not src.exists():
        raise FileNotFoundError("원본 폴더가 없습니다")
    dest_parent.mkdir(parents=True, exist_ok=True)
    name = new_name or src.name
    dest = dest_parent / name
    if dest.exists():
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = dest_parent / f"{name}_{stamp}"
    shutil.move(str(src), str(dest))
    return dest


def move_project_to_stage(src: Path, root: Path, to_stage_id: str) -> Path:
    """단계 이동 시 앨범 하위 구조 유지: 01_음악작업/Album/01곡 → 02_검수대기/Album/01곡."""
    stage = _stage_map().get(to_stage_id)
    if not stage:
        raise ValueError("알 수 없는 단계입니다")
    root_resolved = root.resolve()
    src_resolved = src.resolve()
    try:
        rel_parts = src_resolved.relative_to(root_resolved).parts
    except ValueError:
        rel_parts = (src.name,)
    # [stage, album?, track] or [stage, track]
    if len(rel_parts) >= 3:
        album_name = rel_parts[1]
        dest_parent = root / stage["folder"] / album_name
    else:
        dest_parent = root / stage["folder"]
    return move_project(src, dest_parent)


def export_song_to_stage(
    root: Path,
    stage_id: str,
    project_name: str,
    audio_src: Path | None,
    lyrics_en: str | None,
    lyrics_ko: str | None,
    image_src: Path | None,
    suno_prompt: str | None,
    track_title: str | None = None,
    album_folder: str | None = None,
) -> Path:
    """
    내보내기 경로:
      01_음악작업/<앨범제목>/01 곡제목/
    album_folder 없으면 예전처럼 단계 바로 아래.
    """
    stage = _stage_map().get(stage_id)
    if not stage:
        raise ValueError("알 수 없는 단계입니다")
    if album_folder:
        dest = root / stage["folder"] / _sanitize_folder_title(album_folder) / project_name
    else:
        dest = root / stage["folder"] / project_name
    dest.mkdir(parents=True, exist_ok=True)
    _clear_export_artifacts(dest)

    if audio_src and audio_src.exists():
        shutil.copy2(audio_src, dest / f"audio{audio_src.suffix}")
    if image_src and image_src.exists():
        shutil.copy2(image_src, dest / f"thumbnail{image_src.suffix}")
    if lyrics_en:
        (dest / "lyrics_en.txt").write_text(lyrics_en, encoding="utf-8")
    if lyrics_ko:
        (dest / "lyrics_ko.txt").write_text(lyrics_ko, encoding="utf-8")
    if suno_prompt:
        (dest / "suno_prompt.txt").write_text(suno_prompt, encoding="utf-8")
    (dest / "title.txt").write_text(track_title or project_name, encoding="utf-8")
    return dest
