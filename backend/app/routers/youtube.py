"""YouTube OAuth 및 업로드 API."""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.workflow_service import get_work_root, move_project, resolve_safe_path
from app.services.youtube_service import (
    build_auth_url,
    disconnect_youtube,
    get_stored_video_id,
    get_youtube_public_status,
    handle_oauth_callback,
    publish_video,
    upload_project_video,
)

router = APIRouter(prefix="/youtube", tags=["youtube"])


class YoutubeCredentialsUpdate(BaseModel):
    youtube_client_id: str | None = None
    youtube_client_secret: str | None = None
    redirect_host: str | None = None  # localhost | 127.0.0.1


class YoutubeUploadRequest(BaseModel):
    project_path: str
    privacy_status: str = Field(default="private", description="private | unlisted | public")
    title: str | None = None
    description: str | None = None
    move_to_stage: str | None = Field(default=None, description="업로드 후 이동 단계 (비우면 이동 안 함)")
    tags: list[str] | None = None


class YoutubePublishRequest(BaseModel):
    project_path: str
    video_id: str | None = None
    move_to_stage: str | None = Field(default=None)


@router.get("/status")
async def youtube_status(db: AsyncSession = Depends(get_db)):
    return await get_youtube_public_status(db)


@router.post("/credentials")
async def save_youtube_credentials(
    data: YoutubeCredentialsUpdate, db: AsyncSession = Depends(get_db)
):
    from app.services.settings_service import set_setting
    from app.services.youtube_service import SETTING_REDIRECT_HOST

    if data.youtube_client_id is not None:
        await set_setting(db, "youtube_client_id", data.youtube_client_id.strip())
    if data.youtube_client_secret is not None and data.youtube_client_secret.strip():
        await set_setting(db, "youtube_client_secret", data.youtube_client_secret.strip())
    if data.redirect_host in ("localhost", "127.0.0.1"):
        await set_setting(db, SETTING_REDIRECT_HOST, data.redirect_host)
    return await get_youtube_public_status(db)


@router.get("/auth-url")
async def youtube_auth_url(db: AsyncSession = Depends(get_db)):
    try:
        url = await build_auth_url(db)
        return {"auth_url": url}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/callback", response_class=HTMLResponse)
async def youtube_callback(
    code: str = Query(default=""),
    state: str = Query(default=""),
    error: str = Query(default=""),
    db: AsyncSession = Depends(get_db),
):
    if error:
        return HTMLResponse(
            f"<html><body style='font-family:sans-serif;padding:2rem'>"
            f"<h2>연결 실패</h2><p>{error}</p>"
            f"<p>이 창을 닫고 설정에서 다시 시도하세요.</p></body></html>",
            status_code=400,
        )
    if not code:
        raise HTTPException(400, "인증 코드가 없습니다")
    try:
        info = await handle_oauth_callback(db, code, state)
        title = info.get("channel_title") or "채널"
        return HTMLResponse(
            f"<html><body style='font-family:sans-serif;padding:2rem;text-align:center'>"
            f"<h2>✅ YouTube 연결 완료</h2>"
            f"<p><strong>{title}</strong> 채널이 연결되었습니다.</p>"
            f"<p>이 창을 닫고 Suno Helper로 돌아가세요.</p>"
            f"<script>setTimeout(() => window.close(), 2500)</script>"
            f"</body></html>"
        )
    except ValueError as e:
        return HTMLResponse(
            f"<html><body style='font-family:sans-serif;padding:2rem'>"
            f"<h2>연결 실패</h2><p>{e}</p></body></html>",
            status_code=400,
        )


@router.post("/disconnect")
async def youtube_disconnect(db: AsyncSession = Depends(get_db)):
    await disconnect_youtube(db)
    return {"ok": True}


@router.post("/upload")
async def youtube_upload(req: YoutubeUploadRequest, db: AsyncSession = Depends(get_db)):
    root = await get_work_root(db)
    project = Path(req.project_path)
    if not project.is_absolute():
        project = resolve_safe_path(root, req.project_path)
    if not project.is_dir():
        raise HTTPException(400, "프로젝트 폴더가 아닙니다")

    try:
        result = await upload_project_video(
            db,
            project,
            privacy_status=req.privacy_status,
            title=req.title,
            description=req.description,
            tags=req.tags,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"업로드 실패: {e}")

    if req.move_to_stage:
        from app.services.workflow_service import WORKFLOW_STAGES

        stage = next((s for s in WORKFLOW_STAGES if s["id"] == req.move_to_stage), None)
        if stage:
            dest_parent = root / stage["folder"]
            try:
                move_project(project, dest_parent)
                result["moved_to"] = str(dest_parent / project.name)
            except FileNotFoundError:
                pass

    return result


@router.post("/publish")
async def youtube_publish(req: YoutubePublishRequest, db: AsyncSession = Depends(get_db)):
    root = await get_work_root(db)
    project = Path(req.project_path)
    if not project.is_absolute():
        project = resolve_safe_path(root, req.project_path)

    video_id = req.video_id or get_stored_video_id(project)
    if not video_id:
        raise HTTPException(400, "업로드된 YouTube video_id가 없습니다. 먼저 업로드하세요.")

    try:
        await publish_video(db, video_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"공개 전환 실패: {e}")

    moved_to = None
    if req.move_to_stage and project.is_dir():
        from app.services.workflow_service import WORKFLOW_STAGES

        stage = next((s for s in WORKFLOW_STAGES if s["id"] == req.move_to_stage), None)
        if stage:
            dest_parent = root / stage["folder"]
            try:
                dest = move_project(project, dest_parent)
                moved_to = str(dest)
            except FileNotFoundError:
                pass

    return {
        "video_id": video_id,
        "privacy_status": "public",
        "url": f"https://www.youtube.com/watch?v={video_id}",
        "moved_to": moved_to,
    }


@router.get("/project-meta")
async def youtube_project_meta(
    path: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    root = await get_work_root(db)
    project = resolve_safe_path(root, path) if path else root
    if not project.is_dir():
        raise HTTPException(400, "프로젝트 폴더가 아닙니다")
    video_id = get_stored_video_id(project)
    meta = None
    meta_file = project / "youtube_upload.json"
    if meta_file.exists():
        import json

        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            meta = None
    return {"video_id": video_id, "meta": meta}
