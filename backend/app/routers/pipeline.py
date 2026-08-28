"""로컬 파이프라인·워크플로 API."""

import os
import subprocess
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Song
from app.services.pipeline_defaults import WORKFLOW_STAGES
from app.services.pipeline_queue import enqueue_pipeline_job
from app.services.pipeline_service import detect_video_encoder, find_ffmpeg
from app.services.song_lyrics import lyrics_en_text, lyrics_ko_text
from app.services.workflow_service import (
    browse_directory,
    build_pipeline_project_name,
    export_song_to_stage,
    find_project_assets,
    get_pipeline_config,
    get_work_root,
    init_work_folders,
    list_stages,
    move_project,
    pipeline_relative_path,
    remove_pipeline_project_if_unused,
    resolve_safe_path,
    save_pipeline_config,
    song_display_title,
    WORKFLOW_STAGES as STAGES,
)

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


class PipelineConfigUpdate(BaseModel):
    work_root: Optional[str] = None
    audio: Optional[dict] = None
    video: Optional[dict] = None
    subtitle: Optional[dict] = None
    overlay: Optional[dict] = None


class MoveStageRequest(BaseModel):
    project_path: str
    to_stage: str


class ExportSongRequest(BaseModel):
    song_id: int
    stage_id: str = "music"
    project_name: Optional[str] = None
    language: str = "en"


class RunPipelineRequest(BaseModel):
    project_path: str
    target_stage: str = "review"
    song_id: Optional[int] = None


class OpenFolderRequest(BaseModel):
    path: str


@router.get("/status")
async def pipeline_status():
    ffmpeg = find_ffmpeg()
    encoder = detect_video_encoder("auto") if ffmpeg else None
    return {
        "ffmpeg_available": bool(ffmpeg),
        "detected_encoder": encoder,
        "stages": STAGES,
    }


@router.get("/config")
async def get_config(db: AsyncSession = Depends(get_db)):
    return await get_pipeline_config(db)


@router.patch("/config")
async def update_config(data: PipelineConfigUpdate, db: AsyncSession = Depends(get_db)):
    updates = data.model_dump(exclude_unset=True)
    return await save_pipeline_config(db, updates)


@router.post("/init-folders")
async def api_init_folders(db: AsyncSession = Depends(get_db)):
    result = await init_work_folders(db)
    root = await get_work_root(db)
    return {**result, "work_root": str(root), "stages": list_stages(root)}


@router.get("/stages")
async def api_stages(db: AsyncSession = Depends(get_db)):
    root = await get_work_root(db)
    return {"work_root": str(root), "stages": list_stages(root)}


@router.get("/browse")
async def api_browse(
    path: str = Query(default=""),
    db: AsyncSession = Depends(get_db),
):
    root = await get_work_root(db)
    target = root if not path else resolve_safe_path(root, path)
    try:
        return browse_directory(target, work_root=root)
    except FileNotFoundError:
        raise HTTPException(404, "폴더를 찾을 수 없습니다")
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/assets")
async def api_project_assets(
    path: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    root = await get_work_root(db)
    project = resolve_safe_path(root, path) if path else root
    if not project.is_dir():
        raise HTTPException(400, "프로젝트 폴더가 아닙니다")
    return find_project_assets(project)


@router.get("/media")
async def serve_media(
    path: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    root = await get_work_root(db)
    file_path = Path(path)
    if not file_path.is_absolute():
        file_path = resolve_safe_path(root, path)
    else:
        file_path = file_path.resolve()
        if not str(file_path).startswith(str(root.resolve())):
            raise HTTPException(403, "접근 거부")
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(404, "파일 없음")
    return FileResponse(file_path)


@router.post("/open-folder")
async def open_folder(req: OpenFolderRequest, db: AsyncSession = Depends(get_db)):
    root = await get_work_root(db)
    target = Path(req.path) if Path(req.path).is_absolute() else resolve_safe_path(root, req.path)
    if not target.exists():
        raise HTTPException(404, "경로 없음")
    if os.name == "nt":
        os.startfile(str(target))
    else:
        subprocess.Popen(["xdg-open", str(target)])
    return {"ok": True, "path": str(target)}


@router.post("/move-stage")
async def api_move_stage(req: MoveStageRequest, db: AsyncSession = Depends(get_db)):
    root = await get_work_root(db)
    src = Path(req.project_path)
    if not src.is_absolute():
        src = resolve_safe_path(root, req.project_path)
    stage = next((s for s in STAGES if s["id"] == req.to_stage), None)
    if not stage:
        raise HTTPException(400, "알 수 없는 단계")
    dest_parent = root / stage["folder"]
    try:
        dest = move_project(src, dest_parent)
    except FileNotFoundError:
        raise HTTPException(404, "프로젝트 폴더 없음")
    return {"path": str(dest), "stage": req.to_stage}


@router.post("/export-song")
async def api_export_song(req: ExportSongRequest, db: AsyncSession = Depends(get_db)):
    song = await db.get(Song, req.song_id)
    if not song:
        raise HTTPException(404, "곡 없음")
    root = await get_work_root(db)
    lang = req.language if req.language in ("ko", "en") else "en"
    name = req.project_name or build_pipeline_project_name(song, lang)
    audio = Path(song.audio_path) if song.audio_path else None
    image = Path(song.image_path) if song.image_path else None
    old_pipeline_path = song.pipeline_path
    dest = export_song_to_stage(
        root,
        req.stage_id,
        name,
        audio if audio and audio.exists() else None,
        lyrics_en_text(song),
        lyrics_ko_text(song),
        image if image and image.exists() else None,
        song.suno_prompt,
        track_title=song_display_title(song, lang),
    )
    song.pipeline_path = pipeline_relative_path(root, dest)
    if old_pipeline_path and old_pipeline_path != song.pipeline_path:
        await remove_pipeline_project_if_unused(db, root, old_pipeline_path, {song.id})
    await db.flush()
    return {"path": str(dest), "pipeline_path": song.pipeline_path}


@router.post("/run")
async def api_run_pipeline(req: RunPipelineRequest, db: AsyncSession = Depends(get_db)):
    root = await get_work_root(db)
    project = Path(req.project_path)
    if not project.is_absolute():
        project = resolve_safe_path(root, req.project_path)
    if not project.is_dir():
        raise HTTPException(400, "프로젝트 폴더가 아닙니다")
    assets = find_project_assets(project)
    if not assets["audio_paths"]:
        raise HTTPException(400, "음원 파일이 없습니다 (mp3/wav 등)")
    if not assets["image_paths"]:
        raise HTTPException(400, "썸네일 이미지가 없습니다")
    if not find_ffmpeg():
        raise HTTPException(400, "FFmpeg가 설치되어 있지 않습니다")

    job_id = await enqueue_pipeline_job(str(project), req.target_stage, req.song_id)
    return {"job_id": job_id, "message": "파이프라인 작업이 시작되었습니다"}


@router.get("/workflow-stages")
async def workflow_stage_list():
    return WORKFLOW_STAGES
