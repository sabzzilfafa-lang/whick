"""유튜브 스튜디오 8단계 편집기 API."""

from __future__ import annotations

import logging
import re
import tempfile
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Album
from app.services.audio_fingerprint import has_suno_fingerprint
from app.services.editor_service import (
    apply_style_preset,
    apply_thumbnail_to_project,
    build_youtube_draft,
    create_style_preset,
    delete_style_preset,
    find_latest_video,
    generate_subtitle_preview_frame,
    generate_video_cover_frame,
    generate_thumbnail_preview,
    list_style_presets,
    load_editor_config,
    merge_editor_into_pipeline,
    preview_remaster_audio,
    regenerate_playlist_chapters,
    render_subtitle_preview_video,
    save_editor_config,
    save_youtube_draft,
)
from app.services.workflow_service import find_project_assets, get_pipeline_config, get_work_root, resolve_safe_path

router = APIRouter(prefix="/editor", tags=["editor"])

logger = logging.getLogger(__name__)


class ThumbnailSaveRequest(BaseModel):
    thumbnail: dict


class EditorConfigUpdate(BaseModel):
    mode: Optional[str] = None
    project_paths: Optional[list[str]] = None
    thumbnail: Optional[dict] = None
    subtitle: Optional[dict] = None
    remaster: Optional[dict] = None
    overlay: Optional[dict] = None
    youtube: Optional[dict] = None
    last_step: Optional[int] = None
    style_preset_id: Optional[str] = None


class YoutubeDraftUpdate(BaseModel):
    mode: Optional[str] = None
    title: Optional[str] = None
    subtitle: Optional[str] = None
    description_ko: Optional[str] = None
    description_en: Optional[str] = None
    include_lyrics_in_description: Optional[bool] = None
    tags: Optional[list[str]] = None
    hashtags: Optional[str] = None
    tracks: Optional[list[dict]] = None
    description_locked: Optional[bool] = None
    description_preview: Optional[str] = None
    auto_block: Optional[str] = None


class RegenerateChaptersRequest(BaseModel):
    project_path: str
    project_paths: list[str] = Field(default_factory=list)


class StylePresetCreateRequest(BaseModel):
    name: str
    config: dict = Field(default_factory=dict)  # 현재 에디터 설정(스타일 소스)


class StylePresetApplyRequest(BaseModel):
    preset_id: str


async def _resolve_project(db: AsyncSession, path: str) -> Path:
    root = await get_work_root(db)
    project = Path(path)
    if not project.is_absolute():
        project = resolve_safe_path(root, path)
    if not project.is_dir():
        raise HTTPException(400, "프로젝트 폴더가 아닙니다")
    return project


@router.get("/config")
async def get_editor_config(
    path: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    project = await _resolve_project(db, path)
    assets = find_project_assets(project)
    return {
        "config": load_editor_config(project),
        "assets": {
            "track_title": assets.get("track_title"),
            "has_audio": bool(assets.get("audio_paths")),
            "has_image": bool(assets.get("image_paths")),
            "has_lyrics_en": bool(assets.get("lyrics_en")),
            "has_lyrics_ko": bool(assets.get("lyrics_ko")),
            "image_paths": assets.get("cover_image_paths") or [
                p for p in (assets.get("image_paths") or [])
                if not str(p).lower().endswith("thumbnail.jpg")
            ] or (assets.get("image_paths") or []),
            "all_image_paths": assets.get("image_paths") or [],
            "album_images": assets.get("album_images") or [],
        },
    }


@router.put("/config")
async def put_editor_config(
    path: str = Query(...),
    body: EditorConfigUpdate = ...,
    db: AsyncSession = Depends(get_db),
):
    project = await _resolve_project(db, path)
    updates = body.model_dump(exclude_unset=True)
    cfg = save_editor_config(project, updates)
    return {"config": cfg}


@router.get("/brand")
async def get_brand():
    from app.services.brand_service import load_brand, brand_icon_path, new_icon_token
    from app.services.desc_blocks_service import available_blocks, selected_blocks

    b = load_brand()
    b["icon_url"] = f"/api/editor/brand/icon?v={new_icon_token()}" if brand_icon_path().is_file() else ""
    b["available_blocks"] = available_blocks()
    b["selected_blocks"] = selected_blocks()
    return b


@router.put("/brand")
async def put_brand(body: dict = Body(...)):
    from app.services.brand_service import save_brand
    from app.services.desc_blocks_service import DESCR_BLOCKS

    # desc_blocks 정규화 — 알려진 블록 id만 순서 보존해서 저장
    if "desc_blocks" in body and isinstance(body["desc_blocks"], list):
        body["desc_blocks"] = [i for i in body["desc_blocks"] if i in DESCR_BLOCKS]
    return save_brand(body)


@router.post("/brand/icon")
async def post_brand_icon(file: UploadFile = File(...)):
    """브랜드 아이콘 업로드 — PNG/JPG, 정사각 권장."""
    from app.services.brand_service import save_brand_icon, new_icon_token
    import tempfile

    suffix = Path(file.filename or "icon.png").suffix.lower() or ".png"
    if suffix not in (".png", ".jpg", ".jpeg", ".webp"):
        raise HTTPException(400, "PNG / JPG / WEBP 만 지원합니다")
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(await file.read())
            tmp_path = Path(tmp.name)
        dest = save_brand_icon(tmp_path)
        return {"ok": True, "icon_url": f"/api/editor/brand/icon?v={new_icon_token()}", "size": dest.stat().st_size}
    except Exception as e:
        raise HTTPException(400, f"아이콘 저장 실패: {e}") from e
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except UnboundLocalError:
            pass


@router.delete("/brand/icon")
async def delete_brand_icon():
    from app.services.brand_service import reset_brand_icon, new_icon_token

    removed = reset_brand_icon()
    return {"ok": True, "removed": removed, "icon_url": "", "token": new_icon_token()}


@router.get("/brand/icon")
async def get_brand_icon():
    from app.services.brand_service import brand_icon_path

    p = brand_icon_path()
    if not p.is_file():
        raise HTTPException(404, "아이콘 없음")
    return FileResponse(p, media_type="image/png")


@router.get("/style-presets")
async def api_list_style_presets():
    return {"presets": list_style_presets()}


@router.post("/style-presets")
async def api_create_style_preset(
    path: str = Query(...),
    body: StylePresetCreateRequest = Body(...),
    db: AsyncSession = Depends(get_db),
):
    """현재 곡의 스타일을 프리셋으로 저장 (path는 스타일 출처 곡)."""
    project = await _resolve_project(db, path)
    editor = load_editor_config(project)
    # 프론트가 보내온 현재 편집 상태가 우선 (미저장 변경분 반영)
    source = body.config or editor
    try:
        created = create_style_preset(body.name, source)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"preset": created, **created}


@router.delete("/style-presets/{preset_id}")
async def api_delete_style_preset(preset_id: str):
    try:
        return delete_style_preset(preset_id)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e


@router.post("/style-presets/apply")
async def api_apply_style_preset(
    path: str = Query(...),
    body: StylePresetApplyRequest = Body(...),
    db: AsyncSession = Depends(get_db),
):
    """프리셋을 곡 하나에 적용 — 그 곡의 editor_config에 저장 후 반환."""
    project = await _resolve_project(db, path)
    try:
        cfg = apply_style_preset(project, body.preset_id)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"config": cfg}


@router.post("/preview/thumbnail/render")
async def render_thumbnail_inline(
    path: str = Query(...),
    payload: ThumbnailSaveRequest = Body(...),
    db: AsyncSession = Depends(get_db),
):
    """저장 없이 현재 캔버스를 빠르게 렌더 (미리보기용)."""
    project = await _resolve_project(db, path)
    assets = find_project_assets(project)
    editor = load_editor_config(project)
    thumb = dict(payload.thumbnail or {})
    editor["thumbnail"] = {**(editor.get("thumbnail") or {}), **thumb}
    if isinstance(thumb.get("boxes"), list):
        editor["thumbnail"]["boxes"] = thumb["boxes"]
        editor["thumbnail"]["layout"] = "canvas"
    tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
    tmp.close()
    out = Path(tmp.name)
    try:
        generate_thumbnail_preview(project, editor, out, assets=assets, preview_fast=True)
        return FileResponse(out, media_type="image/jpeg", filename="thumbnail_preview.jpg")
    except Exception as e:
        out.unlink(missing_ok=True)
        raise HTTPException(500, str(e)) from e


@router.get("/preview/thumbnail")
async def preview_thumbnail(
    path: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    project = await _resolve_project(db, path)
    editor = load_editor_config(project)
    tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
    tmp.close()
    out = Path(tmp.name)
    try:
        generate_thumbnail_preview(project, editor, out)
        return FileResponse(out, media_type="image/jpeg", filename="thumbnail_preview.jpg")
    except Exception as e:
        out.unlink(missing_ok=True)
        raise HTTPException(500, str(e)) from e


@router.post("/preview/thumbnail/save")
async def save_thumbnail(
    path: str = Query(...),
    payload: ThumbnailSaveRequest = Body(...),
    db: AsyncSession = Depends(get_db),
):
    project = await _resolve_project(db, path)
    editor = save_editor_config(project, {"thumbnail": payload.thumbnail})
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "thumb.jpg"
        try:
            generate_thumbnail_preview(project, editor, out)
        except Exception as e:
            raise HTTPException(500, f"썸네일 렌더 실패: {e}") from e
        try:
            dest = apply_thumbnail_to_project(project, out)
        except OSError as e:
            raise HTTPException(500, f"thumbnail.jpg 저장 실패: {e}") from e
    return {"ok": True, "path": str(dest), "config": editor}


@router.get("/preview/cover-frame")
async def preview_cover_frame(
    path: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    project = await _resolve_project(db, path)
    tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
    tmp.close()
    out = Path(tmp.name)
    try:
        generate_video_cover_frame(project, out)
        return FileResponse(out, media_type="image/jpeg", filename="cover_frame.jpg")
    except Exception as e:
        out.unlink(missing_ok=True)
        raise HTTPException(500, str(e)) from e


@router.get("/preview/subtitle")
async def preview_subtitle(
    path: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    project = await _resolve_project(db, path)
    global_cfg = await get_pipeline_config(db)
    cfg = merge_editor_into_pipeline(project, global_cfg)
    tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
    tmp.close()
    out = Path(tmp.name)
    try:
        generate_subtitle_preview_frame(project, cfg, out)
        return FileResponse(out, media_type="image/jpeg", filename="subtitle_preview.jpg")
    except Exception as e:
        out.unlink(missing_ok=True)
        raise HTTPException(500, str(e)) from e


@router.get("/preview/audio")
async def preview_audio(
    path: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    project = await _resolve_project(db, path)
    assets = find_project_assets(project)
    if not assets.get("audio_paths"):
        raise HTTPException(400, "음원이 없습니다")
    editor = load_editor_config(project)
    remaster = editor.get("remaster") or {}
    tmp = tempfile.NamedTemporaryFile(suffix=".m4a", delete=False)
    tmp.close()
    out = Path(tmp.name)
    try:
        preview_remaster_audio(Path(assets["audio_paths"][0]), out, remaster, duration_sec=30.0)
        return FileResponse(out, media_type="audio/mp4", filename="preview_audio.m4a")
    except Exception as e:
        out.unlink(missing_ok=True)
        raise HTTPException(500, str(e)) from e


@router.get("/fingerprint-check")
async def fingerprint_check(
    path: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    project = await _resolve_project(db, path)
    root = await get_work_root(db)
    remastered = project / "remastered.m4a"
    video = find_latest_video(project, work_root=root)
    targets = [p for p in (remastered, video) if p and p.exists()]
    results = [
        {"file": p.name, "has_suno": has_suno_fingerprint(p), "path": str(p)}
        for p in targets
    ]
    ok = not any(r["has_suno"] for r in results) if results else None
    return {"ok": ok, "checks": results}


@router.get("/youtube-draft")
async def get_youtube_draft(
    path: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    project = await _resolve_project(db, path)
    return build_youtube_draft(project)


@router.put("/youtube-draft")
async def put_youtube_draft(
    path: str = Query(...),
    body: YoutubeDraftUpdate = ...,
    db: AsyncSession = Depends(get_db),
):
    project = await _resolve_project(db, path)
    payload = body.model_dump(exclude_unset=True)
    return save_youtube_draft(project, payload)


@router.post("/youtube-draft/regenerate-chapters")
async def api_regenerate_chapters(
    body: RegenerateChaptersRequest,
    db: AsyncSession = Depends(get_db),
):
    project = await _project(db, body.project_path)
    root = await get_work_root(db)
    paths = []
    for rel in body.project_paths:
        p = Path(rel)
        if not p.is_absolute():
            p = resolve_safe_path(root, rel)
        paths.append(str(p))
    tracks = regenerate_playlist_chapters(project, paths)
    return {"tracks": tracks}


class PreviewVideoRequest(BaseModel):
    duration_sec: float = 30.0


@router.post("/preview/video")
@router.post("/preview/video/render")
async def render_preview_video(
    path: str = Query(...),
    body: PreviewVideoRequest | None = Body(default=None),
    db: AsyncSession = Depends(get_db),
):
    """자막 위치 확인용 30초 미리보기 영상 인코딩."""
    project = await _resolve_project(db, path)
    global_cfg = await get_pipeline_config(db)
    duration = float((body.duration_sec if body else 30.0) or 30.0)
    try:
        out = render_subtitle_preview_video(project, global_cfg, duration_sec=duration)
        return {"ok": True, "path": str(out), "duration_sec": duration}
    except Exception as e:
        raise HTTPException(500, str(e)) from e


@router.get("/video")
async def get_editor_video(
    path: str = Query(...),
    preview: bool = Query(False),
    db: AsyncSession = Depends(get_db),
):
    project = await _resolve_project(db, path)
    root = await get_work_root(db)
    video = find_latest_video(project, preview=preview, work_root=None if preview else root)
    if not video:
        if preview:
            raise HTTPException(404, "짧은 미리보기 영상이 없습니다. 자막 단계에서 미리보기 렌더를 실행하세요.")
        raise HTTPException(404, "영상이 없습니다. 영상 인코딩 단계에서 렌더를 실행하세요.")
    return FileResponse(video, media_type="video/mp4", filename=video.name)


# ---------------------------------------------------------------------------
# 앨범 썸네일 3종 AI 생성 (2026-09-09)
# 유튜브 Test & Compare는 공개 API가 없어 3종 파일 생성 + 스튜디오 등록 안내 제공
# ---------------------------------------------------------------------------


async def _album_dir(db: AsyncSession, album_id: int) -> tuple[Any, Path]:
    from app.services.thumbnail_ai_service import thumbnails_dir
    from app.services.workflow_service import ensure_album_work_folder

    album = await db.get(Album, album_id)
    if not album:
        raise HTTPException(404, "앨범을 찾을 수 없습니다")
    root = await get_work_root(db)
    try:
        album_dir = ensure_album_work_folder(root, album, "music")
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except OSError as e:
        # 작업폴더 생성 실패(권한·경로) — 순수 500 대신 원인 전달 (2026-09-10)
        raise HTTPException(400, f"작업 폴더 생성 실패: {e}") from e
    except Exception as e:
        logger.error("album work folder failed album=%s: %s", album_id, e, exc_info=True)
        raise HTTPException(500, f"작업 폴더 처리 오류: {str(e)[:200]}") from e
    return album, thumbnails_dir(album_dir)


@router.get("/album-thumbs/{album_id}")
async def list_album_thumbnails(album_id: int, db: AsyncSession = Depends(get_db)):
    """앨범 썸네일 3종(A/B/C) 생성 현황 + URL."""
    from app.services.thumbnail_ai_service import list_generated_thumbnails

    _album, tdir = await _album_dir(db, album_id)
    files = list_generated_thumbnails(tdir.parent)
    for f in files:
        f["url"] = f"/api/editor/album-thumbs/{album_id}/file/{f['variant']}" if f["ready"] else ""
    return {"ok": True, "files": files, "dir": str(tdir)}


@router.get("/album-thumbs/{album_id}/file/{variant}")
async def get_album_thumbnail_file(
    album_id: int, variant: str, db: AsyncSession = Depends(get_db)
):
    """생성된 썸네일 파일 서빙 (variant: A/B/C)."""
    from app.services.thumbnail_ai_service import thumbnails_dir

    if variant not in ("A", "B", "C"):
        raise HTTPException(404, "알 수 없는 변형입니다")
    _album, tdir = await _album_dir(db, album_id)
    p = tdir / f"thumb-{variant}.jpg"
    if not p.is_file():
        raise HTTPException(404, "아직 생성되지 않았습니다")
    return FileResponse(p, media_type="image/jpeg", filename=p.name)


@router.get("/album-thumbs/{album_id}/image-models")
async def list_album_image_models(album_id: int, db: AsyncSession = Depends(get_db)):
    """이미지 생성 AI 모델 목록 — provider별 (설정 화면 선택용, 2026-09-10)."""
    from app.services.thumbnail_ai_service import list_image_models

    try:
        models = await list_image_models(db)
    except Exception as e:
        raise HTTPException(500, f"이미지 모델 목록 조회 실패: {str(e)[:200]}") from e
    return {"ok": True, "models": models}


@router.post("/album-thumbs/{album_id}/prompts")
async def make_album_thumbnail_prompts(
    album_id: int, db: AsyncSession = Depends(get_db)
):
    """앨범 정보로 이미지 생성 프롬프트 3개만 생성 (미리보기용)."""
    from app.services.thumbnail_ai_service import generate_prompts

    album, _tdir = await _album_dir(db, album_id)
    try:
        prompts = await generate_prompts(db, album)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True, "prompts": prompts}


class ThumbnailGenRequest(BaseModel):
    provider: Optional[str] = None  # google | openai (기본: 키 있는 쪽)
    model: Optional[str] = None
    prompts: Optional[list[str]] = None


@router.post("/album-thumbs/{album_id}/generate")
async def generate_album_thumbnails(
    album_id: int,
    body: ThumbnailGenRequest | None = Body(default=None),
    db: AsyncSession = Depends(get_db),
):
    """썸네일 3장 AI 생성 → thumbnails/thumb-A|B|C.jpg 저장."""
    from app.services.thumbnail_ai_service import list_generated_thumbnails
    from app.services.thumbnail_ai_service import generate_thumbnails

    album, tdir = await _album_dir(db, album_id)
    try:
        result = await generate_thumbnails(
            db,
            album,
            provider=body.provider if body else None,
            model=body.model if body else None,
            prompts=body.prompts if body else None,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:  # httpx 등 외부 오류 — URL·키가 섞일 수 있어 정화 후 전달
        # 500 대신 의미 있는 오류 전달 + 로그 남기기 (2026-09-10 파파님 500 원인 규명용)
        logger.error(
            "thumbnail generate failed album=%s provider=%s: %s",
            album_id,
            getattr(body, "provider", None),
            e,
            exc_info=True,
        )
        msg = str(e)[:300]
        msg = re.sub(r"[?&]key=[^&\s'\"]+", "?key=***", msg)
        msg = re.sub(r"sk-[A-Za-z0-9_-]+", "sk-***", msg)
        msg = re.sub(r"(Bearer\s+)\S+", r"\1***", msg)
        raise HTTPException(502, f"이미지 생성 실패: {msg}") from e
    files = list_generated_thumbnails(tdir.parent)
    for f in files:
        f["url"] = f"/api/editor/album-thumbs/{album_id}/file/{f['variant']}" if f["ready"] else ""
    result["files"] = files
    return result


@router.post("/album-thumbs/{album_id}/apply/{variant}")
async def apply_album_thumbnail(
    album_id: int,
    variant: str,
    project_path: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """생성된 썸네일을 곡의 thumbnail.jpg로 적용.

    project_path 미지정 시 앨범 첫 곡의 pipeline_path(내보내기 폴더)를 자동 사용.
    (SongResponse에 pipeline_path가 없어 프론트에서 판단 불가 — bugbot 2026-09-10)
    """
    from app.services.thumbnail_ai_service import thumbnails_dir

    if variant not in ("A", "B", "C"):
        raise HTTPException(404, "알 수 없는 변형입니다")
    album, tdir = await _album_dir(db, album_id)
    src = tdir / f"thumb-{variant}.jpg"
    if not src.is_file():
        raise HTTPException(404, "아직 생성되지 않았습니다")

    if not project_path:
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        # db.get()으로 로드한 Album.songs는 lazy라 async에서 MissingGreenlet 발생 —
        # selectinload로 명시 로드해야 안전 (bugbot 2026-09-10)
        result = await db.execute(
            select(Album)
            .options(selectinload(Album.songs))
            .where(Album.id == album_id)
        )
        fresh = result.scalar_one_or_none()
        if not fresh:
            raise HTTPException(404, "앨범을 찾을 수 없습니다")
        songs = sorted(fresh.songs, key=lambda s: s.track_number)
        target = next((s for s in songs if s.pipeline_path), None)
        if not target or not target.pipeline_path:
            raise HTTPException(
                400,
                "적용할 곡의 작업 폴더가 없습니다. 곡을 내보내기(파이프라인)한 뒤 시도하세요.",
            )
        project_path = target.pipeline_path
    project = await _resolve_project(db, project_path)
    try:
        dest = apply_thumbnail_to_project(project, src)
    except OSError as e:
        raise HTTPException(500, f"thumbnail.jpg 적용 실패: {e}") from e
    return {"ok": True, "path": str(dest), "applied_to": str(project)}
