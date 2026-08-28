"""작업 폴더(D:\\YouTubeMusic) 단계별 워크플로."""

from __future__ import annotations

import json
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
    merged.update(cfg)
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


def list_stages(root: Path) -> list[dict]:
    items = []
    for stage in WORKFLOW_STAGES:
        folder = root / stage["folder"]
        count = 0
        if folder.exists():
            count = sum(1 for p in folder.iterdir() if p.is_dir() and not p.name.startswith("_"))
        items.append({**stage, "path": str(folder), "project_count": count})
    return items


def browse_directory(path: Path, *, work_root: Path | None = None) -> dict:
    if not path.exists():
        raise FileNotFoundError("폴더가 없습니다")
    if not path.is_dir():
        raise ValueError("폴더가 아닙니다")

    stage_folders = {s["folder"] for s in WORKFLOW_STAGES}
    at_work_root = work_root is not None and path.resolve() == work_root.resolve()

    entries = []
    for item in sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        if item.name.startswith(".") or item.name == "_README.txt":
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
            entry["kind"] = "folder"
        entries.append(entry)
    return {"path": str(path), "entries": entries}


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

    images.sort(key=lambda p: (0 if Path(p).name.lower().startswith("thumbnail.") else 1, Path(p).name.lower()))

    if not track_title:
        track_title = project_dir.name

    return {
        "audio_paths": audio,
        "image_paths": images,
        "lyrics_en": lyrics_en,
        "lyrics_ko": lyrics_ko,
        "track_title": track_title,
    }


def pipeline_relative_path(root: Path, project_dir: Path) -> str:
    return str(project_dir.resolve().relative_to(root.resolve())).replace("\\", "/")


def _sanitize_folder_title(title: str) -> str:
    for ch in '/\\:*?"<>|':
        title = title.replace(ch, "-")
    return title.strip(". ") or "untitled"


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
    """작업폴더 프로젝트명: 01 Before I Open My Eyes 형식."""
    track_number = int(getattr(song, "track_number", None) or song.get("track_number") or 1)
    title = song_display_title(song, language)
    return f"{track_number:02d} {title}"


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
) -> Path:
    stage = _stage_map().get(stage_id)
    if not stage:
        raise ValueError("알 수 없는 단계입니다")
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
